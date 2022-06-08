import functools
import re
import urllib.parse

from asgi_webdav.constants import ASGIHeaders, ASGIScope

"""
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/CORS

- https://github.com/simonw/asgi-cors
- https://github.com/encode/starlette/blob/master/starlette/middleware/cors.py
- https://github.com/adamchainz/django-cors-headers
- https://github.com/corydolphin/flask-cors
"""

ALL_METHODS = (b"DELETE", b"GET", b"HEAD", b"OPTIONS", b"PATCH", b"POST", b"PUT")
SAFE_LISTED_HEADERS = {"Accept", "Accept-Language", "Content-Language", "Content-Type"}


class ResponseTextMessage:
    status: int
    headers: ASGIHeaders
    message: str

    def __init__(
        self, message: str, status: int = 200, headers: ASGIHeaders | None = None
    ):
        self.status = status
        self.headers = headers
        self.message = message

    async def __call__(self, scope: ASGIScope, receive, send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": self.headers.list(),
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": self.message.encode("utf-8"),
            }
        )


class ASGIMiddlewareCORS:
    def __init__(
        self,
        app,
        allow_url_regex: str | None = None,
        allow_origins: list[str] = (),
        allow_origin_regex: str | None = None,
        allow_methods: list[str] = ("GET",),
        allow_headers: list[str] = (),
        allow_credentials: bool = False,
        expose_headers: list[str] = (),
        preflight_max_age: int = 600,
    ) -> None:
        if "*" in allow_methods:
            allow_methods = ALL_METHODS
        else:
            allow_methods = [m.encode("utf-8") for m in allow_methods]

        if allow_url_regex is None:
            allow_url_regex_compiled = None
        else:
            allow_url_regex_compiled = re.compile(allow_url_regex)

        if allow_origin_regex is None:
            allow_origin_regex_compiled = None
        else:
            allow_origin_regex_compiled = re.compile(allow_origin_regex)

        allow_all_origins = "*" in allow_origins
        allow_all_headers = "*" in allow_headers
        preflight_explicit_allow_origin = not allow_all_origins or allow_credentials

        simple_headers = ASGIHeaders()
        if allow_all_origins:
            simple_headers[b"Access-Control-Allow-Origin"] = b"*"
        if allow_credentials:
            simple_headers[b"Access-Control-Allow-Credentials"] = b"true"
        if expose_headers:
            simple_headers[b"Access-Control-Expose-Headers"] = ", ".join(
                expose_headers
            ).encode("utf-8")

        preflight_headers = ASGIHeaders()
        if preflight_explicit_allow_origin:
            # The origin value will be set in preflight_response() if it is allowed.
            preflight_headers[b"Vary"] = b"Origin"
        else:
            preflight_headers[b"Access-Control-Allow-Origin"] = b"*"
        preflight_headers.update(
            {
                b"Access-Control-Allow-Methods": b", ".join(allow_methods),
                b"Access-Control-Max-Age": str(preflight_max_age).encode("utf-8"),
            }
        )
        allow_headers = sorted(SAFE_LISTED_HEADERS | set(allow_headers))
        if allow_headers and not allow_all_headers:
            preflight_headers[b"Access-Control-Allow-Headers"] = ", ".join(
                allow_headers
            ).encode("utf-8")
        if allow_credentials:
            preflight_headers[b"Access-Control-Allow-Credentials"] = b"true"

        self.app = app
        self.allow_url_regex = allow_url_regex_compiled
        self.allow_origins = [o.encode("utf-8") for o in allow_origins]
        self.allow_methods = allow_methods
        self.allow_headers = [h.lower().encode("utf-8") for h in allow_headers]
        self.allow_all_origins = allow_all_origins
        self.allow_all_headers = allow_all_headers
        self.preflight_explicit_allow_origin = preflight_explicit_allow_origin
        self.allow_origin_regex = allow_origin_regex_compiled
        self.simple_headers = simple_headers
        self.preflight_headers = preflight_headers

    async def __call__(self, scope: ASGIScope, receive, send) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        headers = ASGIHeaders(scope.get("headers"))
        if headers is None or method is None:  # pragma: no cover
            await self.app(scope, receive, send)
            return

        origin = headers.get(b"origin")

        if origin is None:
            await self.app(scope, receive, send)
            return

        if not self.is_allowed_url(scope):
            await self.app(scope, receive, send)
            return

        if method == "OPTIONS" and b"access-control-request-method" in headers:
            response = self.preflight_response(request_headers=headers)
            await response(scope, receive, send)
            return

        await self.normal_response(scope, receive, send, request_headers=headers)

    def is_allowed_url(self, scope: ASGIScope) -> bool:
        if self.allow_url_regex is None:
            return True

        path = scope.get("path")
        if path is None:
            return False

        path = urllib.parse.unquote(path, encoding="utf-8")
        if self.allow_url_regex.match(path) is None:
            return False

        return True

    def is_allowed_origin(self, origin: bytes) -> bool:
        origin_str = origin.decode("utf-8")
        if self.allow_all_origins:
            return True

        if self.allow_origin_regex is not None and self.allow_origin_regex.match(
            origin_str
        ):
            return True

        return origin in self.allow_origins

    def preflight_response(self, request_headers: ASGIHeaders):
        requested_origin = request_headers[b"origin"]
        requested_method = request_headers[b"access-control-request-method"]
        requested_headers = request_headers.get(b"access-control-request-headers")

        headers = ASGIHeaders()
        headers.update(self.preflight_headers.data)
        failures = []

        if self.is_allowed_origin(origin=requested_origin):
            if self.preflight_explicit_allow_origin:
                # The "else" case is already accounted for in self.preflight_headers
                # and the value would be "*".
                headers[b"Access-Control-Allow-Origin"] = requested_origin
        else:
            failures.append("origin")

        if requested_method not in self.allow_methods:
            failures.append("method")

        # If we allow all headers, then we have to mirror back any requested
        # headers in the response.
        if self.allow_all_headers and requested_headers is not None:
            headers[b"Access-Control-Allow-Headers"] = requested_headers
        elif requested_headers is not None:
            for header in [
                h.lower() for h in requested_headers.decode("utf-8").split(",")
            ]:
                if header.strip().encode("utf-8") not in self.allow_headers:
                    failures.append("headers")
                    break

        # We don't strictly need to use 400 responses here, since its up to
        # the browser to enforce the CORS policy, but its more informative
        # if we do.
        if failures:
            failure_text = "Disallowed CORS " + ", ".join(failures)
            return ResponseTextMessage(failure_text, status=400, headers=headers)

        return ResponseTextMessage("OK", status=200, headers=headers)

    async def normal_response(
        self, scope: ASGIScope, receive, send, request_headers: ASGIHeaders
    ) -> None:
        send = functools.partial(self.send, send=send, request_headers=request_headers)
        await self.app(scope, receive, send)

    async def send(self, message, send, request_headers: ASGIHeaders) -> None:
        if message["type"] != "http.response.start":
            await send(message)
            return

        headers = ASGIHeaders(message.get("headers"))

        headers.update(self.simple_headers.data)
        origin = request_headers[b"origin"]
        has_cookie = b"cookie" in request_headers

        # If request includes any cookie headers, then we must respond
        # with the specific origin instead of '*'.
        if self.allow_all_origins and has_cookie:
            self.allow_explicit_origin(headers, origin)

        # If we only allow specific origins, then we have to mirror back
        # the Origin header in the response.
        elif not self.allow_all_origins and self.is_allowed_origin(origin=origin):
            self.allow_explicit_origin(headers, origin)

        message["headers"] = headers.list()
        await send(message)

    @staticmethod
    def allow_explicit_origin(headers: ASGIHeaders, origin: bytes) -> None:
        headers[b"Access-Control-Allow-Origin"] = origin

        vary = headers.get(b"Vary")
        if vary is not None:
            vary = b", ".join([vary, b"Origin"])
        else:
            vary = b"Origin"

        headers[b"Vary"] = vary
