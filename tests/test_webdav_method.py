from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from asgiref.typing import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendEvent,
    HTTPScope,
)

from asgi_webdav.config import Config, generate_config_from_dict
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE
from asgi_webdav.response import DAVResponse
from asgi_webdav.server import DAVApp

from .kits.asgi import create_asgiref_http_scope_object

CONFIG_OBJECT = {
    "account_mapping": [
        {"username": "username", "password": "password", "permissions": ["+"]},
    ],
    "provider_mapping": [
        {
            "prefix": "/fs",
            "uri": "file://./tests/test_zone",
        },
        {
            "prefix": "/memory",
            "uri": "memory:///",
        },
    ],
}

PROVIDER_NAMES = ("fs", "memory")


async def fake_send(event: ASGISendEvent) -> None:
    return None


class Receive:
    def __init__(self, data: bytes) -> None:
        self.body = data

    async def __call__(self) -> ASGIReceiveEvent:
        body = self.body[:RESPONSE_DATA_BLOCK_SIZE]
        self.body = self.body[RESPONSE_DATA_BLOCK_SIZE:]
        more_body = len(self.body) > 0

        event: ASGIReceiveEvent = {
            "type": "http.request",
            "body": body,
            "more_body": more_body,
        }
        return event


def get_test_config(fs_root: str | None = None) -> Config:
    if fs_root:
        config_object = CONFIG_OBJECT | {
            "provider_mapping": [
                {
                    "prefix": "/fs",
                    "uri": f"file://{fs_root}",
                },
                {
                    "prefix": "/memory",
                    "uri": "memory:///",
                },
            ],
        }
    else:
        config_object = CONFIG_OBJECT

    config = generate_config_from_dict(config_object)
    return config


def get_test_scope(
    method: str,
    data: bytes,
    src_path: str,
    dst_path: str | None = None,
    depth: str | None = None,
) -> tuple[HTTPScope, ASGIReceiveCallable]:
    headers = {
        "authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
        "user-agent": "pytest",
    }
    if dst_path is not None:
        headers.update({"destination": dst_path})
    if depth is not None:
        headers.update({"depth": depth})

    scope = create_asgiref_http_scope_object(
        method=method, path=src_path, headers=headers
    )
    receive = Receive(data)
    return scope, receive


async def get_response_content(response: DAVResponse) -> bytes:
    content = b""
    async for data, more_data in response.content_body_generator:
        content += data
        if not more_data:
            break

    return content


@pytest_asyncio.fixture
async def setup(
    provider_name: str, tmp_path: Path
) -> AsyncIterator[tuple[DAVApp, str]]:
    ut_id = uuid4().hex

    fs_root = tmp_path / "test_zone"
    fs_root.mkdir()

    config = get_test_config(fs_root=str(fs_root))
    dav_app = DAVApp(config)

    # prepare
    base_path = f"/{provider_name}/ut-{ut_id}"

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}")
    _, response = await dav_app.handle(scope, receive, fake_send)

    # run test
    print(f"{ut_id} {provider_name}\n")
    yield dav_app, base_path

    # cleanup
    scope, receive = get_test_scope("DELETE", b"", f"{base_path}")
    _, response = await dav_app.handle(scope, receive, fake_send)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_mkcol_get_head_delete_put(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
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
async def test_method_put_overwrite_updates_length_and_etag(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # macOS Finder creates a file as an empty PUT, then a second PUT with the
    # content: after the overwrite PUT, PROPFIND/GET/HEAD must report the new
    # content-length and a refreshed etag, not the values cached at creation
    server, base_path = setup

    filename = "overwrite_file"
    new_content = uuid4().hex.encode("utf-8")

    # create empty file
    scope, receive = get_test_scope("PUT", b"", f"{base_path}/{filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # GET - empty content, record the etag reported at creation time
    scope, receive = get_test_scope("GET", b"", f"{base_path}/{filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == b""
    assert response.content_length == 0
    etag_created = response.headers[b"ETag"]
    assert isinstance(etag_created, bytes)

    # PUT - overwrite with content
    scope, receive = get_test_scope("PUT", new_content, f"{base_path}/{filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # GET - must report the new length and serve the new content
    scope, receive = get_test_scope("GET", b"", f"{base_path}/{filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == new_content
    assert response.content_length == len(new_content)
    etag_overwritten = response.headers[b"ETag"]
    assert isinstance(etag_overwritten, bytes)
    assert etag_overwritten != etag_created

    # HEAD - must report the refreshed etag as well
    scope, receive = get_test_scope("HEAD", b"", f"{base_path}/{filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert response.headers[b"ETag"] == etag_overwritten


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_move(setup: tuple[DAVApp, str], provider_name: str) -> None:
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    # COPY
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/copy_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "COPY",
        file_content,
        f"{base_path}/copy_file",
        f"{base_path}/copy_file2",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    scope, receive = get_test_scope("GET", b"", f"{base_path}/copy_file2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content

    # MOVE
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/move_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "MOVE",
        file_content,
        f"{base_path}/move_file",
        f"{base_path}/move_file2",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    scope, receive = get_test_scope("GET", b"", f"{base_path}/move_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", f"{base_path}/move_file2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_lock_unlock_exclusive(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    # prepare
    scope, receive = get_test_scope(
        "PUT", file_content, "{}/{}".format(base_path, "lock_unlock")
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # LOCK


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_propfind_includes_resource_itself(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # Depth:1 PROPFIND must include the requested resource itself, aligned
    # with the fs provider: an empty collection or a file has no children,
    # and without the self entry it would report 404 — which blocked macOS
    # Finder from mounting an empty memory provider
    server, base_path = setup

    # empty collection
    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/empty_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "PROPFIND", b"", f"{base_path}/empty_dir", depth="1"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert f"{base_path}/empty_dir".encode() in content

    # file
    file_content = uuid4().hex.encode("utf-8")
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/propfind_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "PROPFIND", b"", f"{base_path}/propfind_file", depth="1"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert f"{base_path}/propfind_file".encode() in content

    # does not exist -> 404 unchanged
    scope, receive = get_test_scope(
        "PROPFIND", b"", f"{base_path}/does_not_exist", depth="1"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404
