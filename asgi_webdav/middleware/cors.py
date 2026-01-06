from __future__ import annotations

import functools
import re
import urllib.parse

from asgiref.typing import (
    ASGI3Application,
    ASGIReceiveCallable,
    ASGISendCallable,
    ASGISendEvent,
    HTTPScope,
)

from asgi_webdav.constants import DAVHeaders

"""
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/CORS

- https://github.com/simonw/asgi-cors
- https://github.com/encode/starlette/blob/master/starlette/middleware/cors.py
- https://github.com/adamchainz/django-cors-headers
- https://github.com/corydolphin/flask-cors
"""

ALL_METHODS = [b"DELETE", b"GET", b"HEAD", b"OPTIONS", b"PATCH", b"POST", b"PUT"]
SAFE_LISTED_HEADERS = {"accept", "accept-language", "content-language", "content-type"}


class ResponseTextMessage:
    message: str
    status: int
    headers: DAVHeaders

    def __init__(self, message: str, status: int, headers: DAVHeaders):
        self.message = message
        self.status = status
        self.headers = headers

    async def __call__(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": self.headers.list(),
                "trailers": True,
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": self.message.encode("utf-8"),
                "more_body": False,
            }
        )


class ASGIMiddlewareCORS:
    def __init__(
        self,
        app: ASGI3Application,
        allow_url_regex: str | None = None,
        allow_origins: list[str] = [],
        allow_origin_regex: str | None = None,
        allow_methods: list[str] = ["GET"],
        allow_headers: list[str] = [],
        allow_credentials: bool = False,
        expose_headers: list[str] = [],
        preflight_max_age: int = 600,
    ) -> None:
        if allow_url_regex is None:
            allow_url_regex_compiled = None
        else:
            allow_url_regex_compiled = re.compile(allow_url_regex)

        if allow_origin_regex is None:
            self.allow_origin_regex = None
        else:
            self.allow_origin_regex = re.compile(allow_origin_regex.encode("utf-8"))

        self.app = app
        self.allow_url_regex = allow_url_regex_compiled

        self.allow_all_origins = "*" in allow_origins
        if self.allow_all_origins:
            self.allow_origins = [b"*"]
        else:
            self.allow_origins = [d.encode("utf-8") for d in allow_origins]

        if "*" in allow_methods:
            self.allow_methods = ALL_METHODS
        else:
            self.allow_methods = [d.encode("utf-8") for d in allow_methods]

        self.allow_all_headers = "*" in allow_headers
        if self.allow_all_headers:
            self.allow_headers = list()
        else:
            self.allow_headers = [
                d.encode("utf-8")
                for d in sorted(
                    SAFE_LISTED_HEADERS | {d.lower() for d in allow_headers}
                )
            ]

        self.preflight_explicit_allow_origin = (
            not self.allow_all_origins or allow_credentials
        )

        simple_headers = DAVHeaders()
        if self.allow_all_origins:
            simple_headers[b"access-control-allow-origin"] = b"*"
        if allow_credentials:
            simple_headers[b"access-control-allow-credentials"] = b"true"
        if expose_headers:
            simple_headers[b"access-control-expose-headers"] = b", ".join(
                [d.lower().encode("utf-8") for d in expose_headers]
                # [d.encode("utf-8") for d in expose_headers]
            )

        preflight_headers = DAVHeaders()
        if self.preflight_explicit_allow_origin:
            # The origin value will be set in preflight_response() if it is allowed.
            preflight_headers[b"vary"] = b"Origin"
        else:
            preflight_headers[b"access-control-allow-origin"] = b"*"
        preflight_headers.update(
            {
                b"access-control-allow-methods": b", ".join(self.allow_methods),
                b"access-control-max-age": str(preflight_max_age).encode("utf-8"),
            }
        )
        if self.allow_headers and not self.allow_all_headers:
            preflight_headers[b"access-control-allow-headers"] = b", ".join(
                self.allow_headers
            )
        if allow_credentials:
            preflight_headers[b"access-control-allow-credentials"] = b"true"

        self.simple_headers = simple_headers
        self.preflight_headers = preflight_headers

    async def __call__(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        if scope["type"] != "http":  # pragma: no cover
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        headers = DAVHeaders(scope.get("headers"))
        if headers is None or method is None:
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

    def is_allowed_url(self, scope: HTTPScope) -> bool:
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
        if self.allow_all_origins:
            return True

        if self.allow_origin_regex is not None and self.allow_origin_regex.match(
            origin
        ):
            return True

        return origin in self.allow_origins

    def preflight_response(self, request_headers: DAVHeaders) -> ResponseTextMessage:
        requested_origin = request_headers[b"origin"]
        requested_method = request_headers[b"access-control-request-method"]
        requested_headers = request_headers[b"access-control-request-headers"]

        headers = DAVHeaders()
        headers.update(self.preflight_headers.data)
        failures = []

        if requested_origin is not None and self.is_allowed_origin(
            origin=requested_origin
        ):
            if self.preflight_explicit_allow_origin:
                # The "else" case is already accounted for in self.preflight_headers
                # and the value would be "*".
                headers[b"access-control-allow-origin"] = requested_origin
        else:
            failures.append("origin")

        if requested_method not in self.allow_methods:
            failures.append("method")

        # If we allow all headers, then we have to mirror back any requested
        # headers in the response.
        if self.allow_all_headers and requested_headers is not None:
            headers[b"access-control-allow-headers"] = requested_headers
        elif requested_headers is not None:
            for header in [
                h.decode("utf-8").lower().strip().encode("utf-8")
                for h in requested_headers.split(b",")
            ]:
                if header not in self.allow_headers:
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
        self,
        scope: HTTPScope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
        request_headers: DAVHeaders,
    ) -> None:
        send = functools.partial(self.send, send=send, request_headers=request_headers)
        await self.app(scope, receive, send)

    async def send(
        self,
        message: ASGISendEvent,
        send: ASGISendCallable,
        request_headers: DAVHeaders,
    ) -> None:
        if message["type"] != "http.response.start":
            await send(message)
            return

        headers = DAVHeaders(message.get("headers"))

        headers.update(self.simple_headers.data)
        origin = request_headers[b"origin"]
        if origin is None:
            # TODO: This should be a 400 response
            raise ValueError("Origin header not found in request")

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
    def allow_explicit_origin(headers: DAVHeaders, origin: bytes) -> None:
        headers[b"access-control-allow-origin"] = origin

        vary = headers.get(b"vary")
        if vary is not None:
            vary = b", ".join([vary, b"Origin"])
        else:
            vary = b"Origin"

        headers[b"vary"] = vary
