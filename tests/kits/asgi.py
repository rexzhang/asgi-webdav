import asyncio
import hashlib
import re
from base64 import b64encode
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from asgiref.typing import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    ASGISendEvent,
    HTTPScope,
)

from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.request import DAVRequest
from asgi_webdav.server import get_asgi_app

HTTPApp = Callable[[HTTPScope, ASGIReceiveCallable, ASGISendCallable], Awaitable[None]]

# Independent RFC 7616-style parameter parser for tests, kept separate
# from the production implementation on purpose.
_DIGEST_CHALLENGE_PARAM_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9_-]*)" r"\s*=\s*" r"(?:\"((?:[^\"\\]|\\.)*)\"" r"|([^\s,]*))"
)


def parse_digest_challenge(challenge: str) -> dict[str, str]:
    """Minimal RFC 7616 challenge parser (handles quoted and unquoted params)."""
    data: dict[str, str] = dict()
    for m in _DIGEST_CHALLENGE_PARAM_RE.finditer(challenge):
        quoted, token = m.group(2), m.group(3)
        if quoted is not None:  # "" is a legal value
            data[m.group(1)] = re.sub(r"\\(.)", r"\1", quoted)
        else:
            data[m.group(1)] = token

    return data


class ASGIFakeSend:
    """Fake ASGI send channel, records events for assertions."""

    status: int = 0
    headers: Iterable[tuple[bytes, bytes]] = tuple()
    trailers: bool = False

    bodys: list[bytes]
    body_content_length: int = 0
    body_calls: int = 0

    on_body: Callable[[], None] | None

    def __init__(self, on_body: Callable[[], None] | None = None) -> None:
        self.bodys = list()
        self.on_body = on_body

    async def __call__(self, event: ASGISendEvent) -> None:
        match event["type"]:
            case "http.response.start":
                self.status = event["status"]
                self.headers = event["headers"]
                self.trailers = event["trailers"]

            case "http.response.trailers":
                self.headers = event["headers"]

            case "http.response.body":
                body = event["body"]
                self.bodys.append(body)
                self.body_calls += 1
                self.body_content_length += len(body)
                if self.on_body is not None:
                    self.on_body()

    def __repr__(self) -> str:
        return (
            f"FakeASGISend(): {self.status}, {self.headers}, {self.trailers}, "
            f"body * {len(self.bodys)}, calls * {self.body_calls}"
        )


class ASGIFakeReceive:
    """Fake ASGI receive channel for disconnect tests.

    The first call returns a leftover http.request event; later calls block
    until trigger_disconnect() is called, then return http.disconnect.
    """

    call_count: int = 0

    def __init__(self) -> None:
        self._disconnect_event = asyncio.Event()

    def trigger_disconnect(self) -> None:
        self._disconnect_event.set()

    async def __call__(self) -> ASGIReceiveEvent:
        self.call_count += 1
        if self.call_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}

        await self._disconnect_event.wait()
        return {"type": "http.disconnect"}


async def fake_receive() -> ASGIReceiveEvent:
    return {"type": "http.request", "body": b"", "more_body": False}


async def fake_send(event: ASGISendEvent) -> None:
    return


def create_asgiref_http_scope_object(
    method: str = "GET",
    path: str = "/",
    # Sequence instead of Iterable: dict is not a Sequence, so both
    # mypy and Pyright narrow the dict branch of this union cleanly
    headers: (
        Sequence[tuple[bytes, bytes]] | dict[str, str] | dict[bytes, bytes] | None
    ) = None,
) -> HTTPScope:
    converted: list[tuple[bytes, bytes]] = []
    if headers is None:
        pass
    elif isinstance(headers, dict):
        for k, v in headers.items():
            key: bytes = k.encode("utf-8") if isinstance(k, str) else k
            value: bytes = v.encode("utf-8") if isinstance(v, str) else v
            converted.append((key, value))
    else:
        converted.extend(headers)

    data: HTTPScope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": b"",
        "query_string": b"",
        "root_path": "",
        "headers": converted,
        "client": None,
        "server": None,
        "extensions": {},
    }

    return data


def create_dav_request_object(
    method: str = "GET",
    path: str = "/",
    headers: Sequence[tuple[bytes, bytes]] | dict[str, str] | None = None,
) -> DAVRequest:
    return DAVRequest(
        scope=create_asgiref_http_scope_object(
            method=method, path=path, headers=headers
        ),
        receive=fake_receive,
        send=fake_send,
    )


def get_webdav_app(config_object: dict[str, Any]) -> HTTPApp:
    # the middleware chain is a valid ASGI app at runtime, but some members
    # (e.g. SentryAsgiMiddleware) are not statically assignable to HTTPApp
    return cast(
        HTTPApp,
        get_asgi_app(
            AppEntryParameters(), generate_config_from_dict(config_object).to_dict()
        ),
    )


class ASGIApp:
    def __init__(self, app_response_header: dict[bytes, bytes] | None = None) -> None:
        self.app_response_header = app_response_header or dict()

    async def __call__(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        assert scope["type"] == "http"

        headers = {b"Content-Type": b"text/plain"}
        if self.app_response_header:
            headers.update(self.app_response_header)

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(k, v) for k, v in headers.items()],
                "trailers": False,
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Hello, World!",
                "more_body": False,
            }
        )


@dataclass
class ASGIRequest:
    method: str
    path: str
    headers: dict[bytes, bytes]
    data: bytes

    def get_scope(self) -> HTTPScope:
        return create_asgiref_http_scope_object(
            method=self.method,
            path=self.path,
            headers=[(k.lower(), v) for k, v in self.headers.items()],
        )


@dataclass
class ASGIResponse:
    status_code: int = 200
    _headers: dict[bytes, bytes] = field(default_factory=dict)
    data: bytes = b""

    @property
    def headers(self) -> dict[bytes, bytes]:
        return self._headers

    @headers.setter
    def headers(self, data: Iterable[tuple[bytes, bytes]]) -> None:
        self._headers = {k.decode("utf-8").lower().encode("utf-8"): v for k, v in data}

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


class ASGITestClient:
    request: ASGIRequest
    response: ASGIResponse

    def __init__(self, app: HTTPApp) -> None:
        self.app = app

    async def _fake_receive(self) -> ASGIReceiveEvent:
        return {
            "type": "http.request",
            "body": self.request.data,
            "more_body": False,
        }

    async def _fake_send(self, event: ASGISendEvent) -> None:
        match event["type"]:
            case "http.response.start":
                self.response.status_code = event["status"]
                self.response.headers = event["headers"]

            case "http.response.body":
                self.response.data = event["body"]

            case _:
                raise NotImplementedError

    async def _call_method(self) -> ASGIResponse:
        headers = {b"user-agent": b"ASGITestClient"}
        headers.update(self.request.headers)
        self.request.headers = headers

        self.response = ASGIResponse()
        await self.app(
            self.request.get_scope(),
            self._fake_receive,
            self._fake_send,
        )

        return self.response

    @staticmethod
    def create_basic_authorization_headers(
        username: str, password: str
    ) -> dict[bytes, bytes]:
        credentials = b64encode(f"{username}:{password}".encode()).decode("utf-8")
        return {b"authorization": f"Basic {credentials}".encode()}

    @staticmethod
    def create_digest_authorization_headers(
        method: str,
        uri: str,
        challenge: str,
        username: str,
        *,
        password: str | None = None,
        ha1: str | None = None,
        nc: str = "00000001",
        cnonce: str = "0a4f113b",
        neon_style: bool = True,
    ) -> dict[bytes, bytes]:
        """Build a Digest Authorization header from a WWW-Authenticate
        challenge value.

        neon_style=True mimics neon 0.31.x (WinSCP): algorithm/qop sent
        quoted, nc unquoted. neon_style=False follows the RFC 7616 grammar
        strictly: algorithm/qop as unquoted tokens.
        """
        params = parse_digest_challenge(challenge.removeprefix("Digest "))
        realm = params["realm"]
        nonce = params["nonce"]
        opaque = params.get("opaque", "")
        qop = params.get("qop", "")

        if ha1 is None:
            if password is None:
                raise ValueError("password or ha1 is required")
            ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()

        ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
        if qop == "auth":
            response = hashlib.md5(
                f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}".encode()
            ).hexdigest()
        else:
            # RFC 2069 legacy
            response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

        def _q(value: str) -> str:
            return f'"{value}"'

        algorithm = '"MD5"' if neon_style else "MD5"
        qop_value = '"auth"' if neon_style else "auth"

        parts: list[str] = [
            f"username={_q(username)}",
            f"realm={_q(realm)}",
            f"nonce={_q(nonce)}",
            f"uri={_q(uri)}",
            f"algorithm={algorithm}",
            f"response={_q(response)}",
        ]
        if opaque:
            parts.append(f"opaque={_q(opaque)}")
        if qop == "auth":
            parts.append(f"cnonce={_q(cnonce)}")
            parts.append(f"nc={nc}")
            parts.append(f"qop={qop_value}")

        return {b"authorization": f"Digest {', '.join(parts)}".encode()}

    async def get(
        self, path: str, headers: dict[bytes, bytes] | None = None
    ) -> ASGIResponse:
        self.request = ASGIRequest("GET", path, headers or dict(), b"")
        return await self._call_method()

    async def options(
        self, path: str, headers: dict[bytes, bytes] | None = None
    ) -> ASGIResponse:
        self.request = ASGIRequest("OPTIONS", path, headers or dict(), b"")
        return await self._call_method()
