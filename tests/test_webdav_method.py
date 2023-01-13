from collections.abc import Callable
from uuid import uuid4

import pytest
import pytest_asyncio

from asgi_webdav.config import Config, get_config, init_config_from_obj
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE, ASGIScope
from asgi_webdav.response import DAVResponse
from asgi_webdav.server import Server

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


async def fake_send():
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
    init_config_from_obj(CONFIG_OBJECT)
    config = get_config()
    return config


def get_test_scope(
    method: str, data: bytes, src_path: str, dst_path: str | None = None
) -> (ASGIScope, Callable):
    headers = {
        b"authorization": b"Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
        b"user-agent": b"pytest",
    }
    if dst_path is not None:
        headers.update({b"destination": dst_path.encode("utf-8")})

    scope = ASGIScope({"method": method, "headers": headers, "path": src_path})
    receive = Receive(data)
    return scope, receive


async def get_response_content(response: DAVResponse) -> bytes:
    content = b""
    async for data, more_data in response.content:
        content += data
        if not more_data:
            break

    return content


@pytest_asyncio.fixture
async def setup(provider_name):
    ut_id = uuid4().hex
    config = get_test_config()
    server = Server(config)

    # prepare
    base_path = f"/{provider_name}/ut-{ut_id}"

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}")
    _, response = await server.handle(scope, receive, fake_send)

    # run test
    print(f"{ut_id} {provider_name}\n")
    yield server, base_path

    # cleanup
    scope, receive = get_test_scope("DELETE", b"", f"{base_path}")
    _, response = await server.handle(scope, receive, fake_send)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_mkcol_get_head_delete_put(setup, provider_name):
    server, base_path = setup

    put_filename = "put_file"
    file_content = uuid4().hex.encode("utf-8")

    # GET - does not exist
    scope, receive = get_test_scope("GET", b"", f"{base_path}/does_not_exist")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404
    assert response.content_length == 0

    # HEAD - does not exist
    scope, receive = get_test_scope("HEAD", b"", f"{base_path}/does_not_exist")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404
    assert response.content_length == 0

    # GET - dir
    scope, receive = get_test_scope("GET", b"", f"{base_path}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert response.content_length == 0

    # HEAD  - dir
    scope, receive = get_test_scope("HEAD", b"", f"{base_path}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert response.content_length == 0

    # PUT - file
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # GET - file
    scope, receive = get_test_scope("GET", b"", f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content

    # HEAD - file
    scope, receive = get_test_scope("HEAD", b"", f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == b""
    assert response.content_length == 0

    # PUT - file - overwrite # TODO?
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # DELETE
    scope, receive = get_test_scope(
        "DELETE", file_content, f"{base_path}/{put_filename}"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    # DELETE - 404
    scope, receive = get_test_scope(
        "DELETE", file_content, f"{base_path}/{put_filename}"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_move(setup, provider_name):
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    # COPY
    scope, receive = get_test_scope(
        "PUT", file_content, "{}/{}".format(base_path, "copy_file")
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "COPY",
        file_content,
        "{}/{}".format(base_path, "copy_file"),
        "{}/{}".format(base_path, "copy_file2"),
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", "{}/{}".format(base_path, "copy_file2"))
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content

    # MOVE
    scope, receive = get_test_scope(
        "PUT", file_content, "{}/{}".format(base_path, "move_file")
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "MOVE",
        file_content,
        "{}/{}".format(base_path, "move_file"),
        "{}/{}".format(base_path, "move_file2"),
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", "{}/{}".format(base_path, "move_file"))
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", "{}/{}".format(base_path, "move_file2"))
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_lock_unlock_exclusive(setup, provider_name):
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    # prepare
    scope, receive = get_test_scope(
        "PUT", file_content, "{}/{}".format(base_path, "lock_unlock")
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # LOCK
