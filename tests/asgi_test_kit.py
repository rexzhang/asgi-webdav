from base64 import b64encode
from dataclasses import dataclass

import pytest
from icecream import ic

from asgi_webdav.constants import ASGIScope


class ASGIApp:
    def __init__(self, app_response_header: dict[str, str] = None):
        self.app_response_header = app_response_header

    async def __call__(self, scope: ASGIScope, receive, send):
        assert scope["type"] == "http"

        headers = {"Content-Type": "text/plain"}
        if self.app_response_header is not None:
            headers.update(self.app_response_header)

        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (k.encode("utf-8"), v.encode("utf-8")) for k, v in headers.items()
                ],
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
    headers: dict[str, str]
    data: bytes

    def get_scope(self):
        return {
            "type": "http",
            "method": self.method,
            "headers": [
                (item[0].lower().encode("utf-8"), item[1].encode("utf-8"))
                for item in self.headers.items()
            ],
            "path": self.path,
        }


@dataclass
class ASGIResponse:
    status_code: int | None = None
    _headers: dict[str, str] | None = None
    data: bytes | None = None

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @headers.setter
    def headers(self, data: list[tuple[bytes, bytes]]):
        ic("header in respone", data)
        self._headers = dict()
        try:
            for k, v in data:
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                else:
                    raise Exception("type(Key:{}) isn't bytes: {}".format(k, data))
                if isinstance(v, bytes):
                    v = v.decode("utf-8")
                else:
                    raise Exception("type(Value:{}) isn't bytes: {}".format(v, data))

                self._headers[k.lower()] = v
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
                raise NotImplementedError()

        return

    async def _call_method(self) -> ASGIResponse:
        ic("input", self.request)
        headers = {
            "user-agent": "ASGITestClient",
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
    ) -> dict[str, str]:
        return {
            "authorization": "Basic {}".format(
                b64encode("{}:{}".format(username, password).encode("utf-8")).decode(
                    "utf-8"
                )
            )
        }

    async def get(self, path, headers: dict[str, str] = None) -> ASGIResponse:
        if headers is None:
            headers = dict()
        self.request = ASGIRequest("GET", path, headers, b"")
        return await self._call_method()

    async def options(self, path, headers: dict[str, str]) -> ASGIResponse:
        self.request = ASGIRequest("OPTIONS", path, headers, b"")
        return await self._call_method()


@pytest.mark.asyncio
async def test_base():
    client = ASGITestClient(ASGIApp())
    response = await client.get("/")
    assert response.status_code == 200
