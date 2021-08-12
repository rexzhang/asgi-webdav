from typing import Optional, Callable
from uuid import uuid4

import pytest

from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE
from asgi_webdav.config import Config, get_config, update_config_from_obj
from asgi_webdav.exception import NotASGIRequestException
from asgi_webdav.server import Server
from asgi_webdav.response import DAVResponse


CONFIG_OBJECT = {
    "account_mapping": [
        {"username": "username", "password": "password", "permissions": ["+"]},
    ],
    "provider_mapping": [
        {
            "prefix": "/fs",
            "uri": "file://./test_zone",
        },
        {
            "prefix": "/memory",
            "uri": "memory:///",
        },
    ],
}

PROVIDER_NAMES = ("fs", "memory")


async def fake_call():
    return


async def send():
    return


class Receive:
    def __init__(self, data):
        self.body = data

    async def __call__(self):
        body = self.body[:RESPONSE_DATA_BLOCK_SIZE]
        self.body = self.body[RESPONSE_DATA_BLOCK_SIZE:]
        more_body = len(self.body) > 0

        return {
            "body": body,
            "more_body": more_body,
        }


def get_test_config() -> Config:
    update_config_from_obj(CONFIG_OBJECT)
    config = get_config()
    return config


def get_test_scope(
    method: str, data: bytes, src_path: str, dst_path: Optional[str] = None
) -> (dict, Callable):
    headers = {
        b"authorization": b"Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
        b"user-agent": b"pytest",
    }
    if dst_path is not None:
        headers.update({b"destination": dst_path.encode("utf-8")})

    scope = {"method": method, "headers": headers, "path": src_path}
    receive = Receive(data)
    return scope, receive


async def get_response_content(response: DAVResponse) -> bytes:
    content = b""
    async for data, more_data in response.content:
        content += data
        if not more_data:
            break

    return content


@pytest.mark.asyncio
async def test_request_parser():
    config = get_test_config()
    server = Server(config)

    with pytest.raises(NotASGIRequestException):
        await server.handle({}, fake_call, send)


@pytest.mark.asyncio
async def test_method_mkcol_get_head_delete_put():
    config = get_test_config()
    server = Server(config)

    file_content = uuid4().hex.encode("utf-8")
    put_filename = "put_file"
    ut_id = uuid4().hex

    for provider_name in PROVIDER_NAMES:
        # prepare
        base_path = "/{}/ut-{}".format(provider_name, ut_id)

        scope, receive = get_test_scope("MKCOL", b"", "{}".format(base_path))
        _, response = await server.handle(scope, receive, send)
        assert response.status == 201

        # GET - does not exist
        scope, receive = get_test_scope(
            "GET", b"", "{}/does_not_exist".format(base_path)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 404
        assert response.content_length == 0

        # HEAD - does not exist
        scope, receive = get_test_scope(
            "HEAD", b"", "{}/does_not_exist".format(base_path)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 404
        assert response.content_length == 0

        # GET - dir
        scope, receive = get_test_scope("GET", b"", "{}".format(base_path))
        _, response = await server.handle(scope, receive, send)
        assert response.status == 200
        assert response.content_length == 0

        # HEAD  - dir
        scope, receive = get_test_scope("HEAD", b"", "{}".format(base_path))
        _, response = await server.handle(scope, receive, send)
        assert response.status == 200
        assert response.content_length == 0

        # PUT - file
        scope, receive = get_test_scope(
            "PUT", file_content, "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 201

        # GET - file
        scope, receive = get_test_scope(
            "GET", b"", "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 200
        assert await get_response_content(response) == file_content

        # HEAD - file
        scope, receive = get_test_scope(
            "HEAD", b"", "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 200
        assert await get_response_content(response) == b""
        assert response.content_length == 0

        # PUT - file - overwrite # TODO?
        scope, receive = get_test_scope(
            "PUT", file_content, "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 201

        # DELETE
        scope, receive = get_test_scope(
            "DELETE", file_content, "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 204

        # DELETE - 404
        scope, receive = get_test_scope(
            "DELETE", file_content, "{}/{}".format(base_path, put_filename)
        )
        _, response = await server.handle(scope, receive, send)
        assert response.status == 404

        # cleanup
        scope, receive = get_test_scope("DELETE", file_content, "{}".format(base_path))
        _, response = await server.handle(scope, receive, send)
        assert response.status == 204
