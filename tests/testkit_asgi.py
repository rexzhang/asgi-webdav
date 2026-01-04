from base64 import b64encode
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from asgiref.typing import HTTPScope
from icecream import ic

from asgi_webdav.config import generate_config_from_dict
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.request import DAVRequest
from asgi_webdav.server import get_asgi_app


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
    headers: Iterable[tuple[bytes, bytes]] | dict[str, str] | None = None,
) -> HTTPScope:
    match headers:
        case None:
            headers = []
        case dict():
            headers = [
                (k.encode("utf-8"), v.encode("utf-8")) for k, v in headers.items()  # type: ignore
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
