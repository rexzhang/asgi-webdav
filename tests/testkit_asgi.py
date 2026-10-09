import hashlib
import re
from base64 import b64encode
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from asgiref.typing import HTTPScope
from icecream import ic

from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.request import DAVRequest
from asgi_webdav.server import get_asgi_app

# Independent RFC 7616-style parameter parser for tests, kept separate
# from the production implementation on purpose.
_DIGEST_CHALLENGE_PARAM_RE = re.compile(
    r"([a-zA-Z][a-zA-Z0-9_-]*)" r"\s*=\s*" r"(?:\"((?:[^\"\\]|\\.)*)\"" r"|([^\s,]*))"
)


def parse_digest_challenge(challenge: str) -> dict[str, str]:
    """Minimal RFC 7616 challenge parser, intentionally independent of
    production code (regex handles quoted and unquoted params)."""
    data: dict[str, str] = dict()
    for m in _DIGEST_CHALLENGE_PARAM_RE.finditer(challenge):
        quoted, token = m.group(2), m.group(3)
        if quoted is not None:  # "" is a legal value
            data[m.group(1)] = re.sub(r"\\(.)", r"\1", quoted)
        else:
            data[m.group(1)] = token

    return data


class ASGIApp:
    def __init__(self, app_response_header: dict[bytes, bytes] = {}):
        self.app_response_header = app_response_header

    async def __call__(self, scope: HTTPScope, receive: Callable, send: Callable):
        assert scope["type"] == "http"

        headers = {b"Content-Type": b"text/plain"}
        if self.app_response_header:
            headers.update(self.app_response_header)

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(k, v) for k, v in headers.items()],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"Hello, World!",
            }
        )


@dataclass
class ASGIRequest:
    method: str
    path: str
    headers: dict[bytes, bytes]
    data: bytes

    def get_scope(self):
        return {
            "type": "http",
            "method": self.method,
            "headers": [
                (k.decode("utf-8").lower().encode("utf-8"), v)
                for k, v in self.headers.items()
            ],
            "path": self.path,
        }


@dataclass
class ASGIResponse:
    status_code: int = 200
    _headers: dict[bytes, bytes] = field(default_factory=dict)
    data: bytes = b""

    @property
    def headers(self) -> dict[bytes, bytes]:
        return self._headers

    @headers.setter
    def headers(self, data: list[tuple[bytes, bytes]]):
        ic("header in respone", data)
        self._headers = dict()
        try:
            for k, v in data:
                if isinstance(k, bytes):
                    k = k
                else:
                    raise Exception(f"type(Key:{k}) isn't bytes: {data}")
                if isinstance(v, bytes):
                    v = v
                else:
                    raise Exception(f"type(Value:{v}) isn't bytes: {data}")

                self._headers[k.decode("utf-8").lower().encode("utf-8")] = v
        except ValueError as e:
            raise ValueError(e, data)

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


class ASGITestClient:
    request: ASGIRequest
    response: ASGIResponse

    def __init__(
        self,
        app,
    ):
        self.app = app

    async def _fake_receive(self):
        return self.request.data

    async def _fake_send(self, data: dict):
        match data["type"]:
            case "http.response.start":
                self.response.status_code = data["status"]
                self.response.headers = data["headers"]

            case "http.response.body":
                self.response.data = data["body"]

            case _:
                raise NotImplementedError

        return

    async def _call_method(self) -> ASGIResponse:
        ic("input", self.request)
        headers = {
            b"user-agent": b"ASGITestClient",
        }
        headers.update(self.request.headers)
        self.request.headers = headers
        ic("prepare", self.request)

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
        return {
            b"authorization": "Basic {}".format(
                b64encode(f"{username}:{password}".encode()).decode("utf-8")
            ).encode("utf-8")
        }

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

    async def get(self, path: str, headers: dict[bytes, bytes] = {}) -> ASGIResponse:
        self.request = ASGIRequest("GET", path, headers, b"")
        return await self._call_method()

    async def options(self, path, headers: dict[bytes, bytes]) -> ASGIResponse:
        self.request = ASGIRequest("OPTIONS", path, headers, b"")
        return await self._call_method()


async def fake_call():
    pass


async def fake_send():
    return


def create_asgiref_http_scope_object(
    method: str = "GET",
    path: str = "/",
    headers: (
        Iterable[tuple[bytes, bytes]] | dict[str, str] | dict[bytes, bytes] | None
    ) = None,
) -> HTTPScope:
    match headers:
        case None:
            headers = []
        case dict():
            headers = [
                (k.encode("utf-8"), v.encode("utf-8")) if isinstance(k, str) else (k, v)
                for k, v in headers.items()  # type: ignore
            ]

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
        "headers": headers,
        "client": None,
        "server": None,
        "extensions": {},
    }

    return data


def create_dav_request_object(
    method: str = "GET",
    path: str = "/",
    headers: Iterable[tuple[bytes, bytes]] | dict[str, str] | None = None,
) -> DAVRequest:
    return DAVRequest(
        scope=create_asgiref_http_scope_object(
            method=method, path=path, headers=headers
        ),
        receive=fake_call,
        send=fake_call,
    )


def get_webdav_app(config_object: dict):
    return get_asgi_app(
        AppEntryParameters(), generate_config_from_dict(config_object).to_dict()
    )
