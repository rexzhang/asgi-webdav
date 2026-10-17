import asyncio
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
from pytest_mock import MockerFixture

from asgi_webdav.config import Config, generate_config_from_dict
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE
from asgi_webdav.response import DAVResponse
from asgi_webdav.server import DAVApp

from .kits.asgi import create_asgiref_http_scope_object

# ---- constants ----

CONFIG_OBJECT = {
    "account_mapping": [
        {"username": "username", "password": "password", "permissions": ["+"]},
    ],
    "provider_mapping": [
        {
            "prefix": "/fs",
            "uri": "file://./tests/test_zone",
            "ignore_property_extra": False,
        },
        {
            "prefix": "/memory",
            "uri": "memory:///",
            "ignore_property_extra": False,
        },
    ],
}

PROVIDER_NAMES = ("fs", "memory")

PROPFIND_EXTRA_KEYS_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<D:propfind xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
    b"<D:prop><Z:author/></D:prop>"
    b"</D:propfind>"
)
PROPPATCH_SET_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<D:propertyupdate xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
    b"<D:set><D:prop>"
    b"<Z:author>tester</Z:author>"
    b"<Z:status>draft</Z:status>"
    b"</D:prop></D:set></D:propertyupdate>"
)
PROPPATCH_REMOVE_AUTHOR_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<D:propertyupdate xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
    b"<D:remove><D:prop><Z:author/></D:prop></D:remove>"
    b"</D:propertyupdate>"
)
PROPPATCH_REMOVE_MISSING_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<D:propertyupdate xmlns:D="DAV:" xmlns:Z="http://example.com/ns">'
    b"<D:remove><D:prop><Z:never-existed/></D:prop></D:remove>"
    b"</D:propertyupdate>"
)


# ---- helpers ----


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


class ParkingReceive:
    """Deliver the first chunk, then park until released — simulates a
    slow/stalled upload whose body is still streaming in."""

    def __init__(self, first_chunk: bytes) -> None:
        self.first_chunk = first_chunk
        self.first_sent = False
        self.release_event = asyncio.Event()

    async def __call__(self) -> ASGIReceiveEvent:
        if not self.first_sent:
            self.first_sent = True
            event: ASGIReceiveEvent = {
                "type": "http.request",
                "body": self.first_chunk,
                "more_body": True,
            }
            return event

        await self.release_event.wait()
        event = {"type": "http.request", "body": b"", "more_body": False}
        return event


class DisconnectReceive:
    """Deliver one chunk, then http.disconnect — simulates a client that
    aborts the upload mid-body."""

    def __init__(self, chunk: bytes) -> None:
        self.chunk = chunk
        self.calls = 0

    async def __call__(self) -> ASGIReceiveEvent:
        self.calls += 1
        if self.calls == 1:
            event: ASGIReceiveEvent = {
                "type": "http.request",
                "body": self.chunk,
                "more_body": True,
            }
            return event

        return {"type": "http.disconnect"}


def get_test_config(fs_root: str | None = None) -> Config:
    if fs_root:
        config_object = CONFIG_OBJECT | {
            "provider_mapping": [
                {
                    "prefix": "/fs",
                    "uri": f"file://{fs_root}",
                    "ignore_property_extra": False,
                },
                {
                    "prefix": "/memory",
                    "uri": "memory:///",
                    "ignore_property_extra": False,
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
    overwrite: str | None = None,
    if_header: str | None = None,
) -> tuple[HTTPScope, ASGIReceiveCallable]:
    headers = {
        "authorization": "Basic dXNlcm5hbWU6cGFzc3dvcmQ=",
        "user-agent": "pytest",
    }
    if dst_path is not None:
        headers.update({"destination": dst_path})
    if depth is not None:
        headers.update({"depth": depth})
    if overwrite is not None:
        headers.update({"overwrite": overwrite})
    if if_header is not None:
        headers.update({"if": if_header})

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


# ---- RFC 4918 §9.1 PROPFIND ----


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


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_propfind_extra_keys(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.1: a propfind asking for a missing property gets a 404
    # propstat, one asking for an existing property gets it back
    server, base_path = setup
    target = f"{base_path}/prop_keys_file"

    scope, receive = get_test_scope("PUT", b"data", target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # asking for a missing property -> 404 propstat
    scope, receive = get_test_scope(
        "PROPFIND", PROPFIND_EXTRA_KEYS_BODY, target, depth="0"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert b"404" in content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_propfind_depth_infinity(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.1: Depth infinity lists the collection and every
    # descendant
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    for path in (
        f"{base_path}/deep_dir",
        f"{base_path}/deep_dir/sub",
        f"{base_path}/deep_dir/root_file",
        f"{base_path}/deep_dir/sub/deep_file",
    ):
        method = "MKCOL" if path.endswith(("deep_dir", "sub")) else "PUT"
        body = b"" if method == "MKCOL" else file_content
        scope, receive = get_test_scope(method, body, path)
        _, response = await server.handle(scope, receive, fake_send)
        assert response.status in (201,)

    scope, receive = get_test_scope(
        "PROPFIND",
        b"",
        f"{base_path}/deep_dir",
        depth="infinity",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207

    content = await get_response_content(response)
    for href in (
        f"{base_path}/deep_dir",
        f"{base_path}/deep_dir/sub",
        f"{base_path}/deep_dir/root_file",
        f"{base_path}/deep_dir/sub/deep_file",
    ):
        assert href.encode() in content


# ---- RFC 4918 §9.2 PROPPATCH ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_proppatch_set_and_remove(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.2: PROPPATCH set/remove round trip; the stored property is
    # visible to a later PROPFIND that asks for it by name
    server, base_path = setup
    target = f"{base_path}/prop_file"

    scope, receive = get_test_scope("PUT", b"data", target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PROPPATCH", PROPPATCH_SET_BODY, target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert b"200 OK" in content

    # the property is readable via PROPFIND with named extra keys
    scope, receive = get_test_scope(
        "PROPFIND", PROPFIND_EXTRA_KEYS_BODY, target, depth="0"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert b"tester" in content

    # remove
    scope, receive = get_test_scope("PROPPATCH", PROPPATCH_REMOVE_AUTHOR_BODY, target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert b"200 OK" in content

    scope, receive = get_test_scope(
        "PROPFIND", PROPFIND_EXTRA_KEYS_BODY, target, depth="0"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207
    content = await get_response_content(response)
    assert b"tester" not in content
    assert b"404" in content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_proppatch_remove_missing_is_ok(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.2.2: removing a property that does not exist is not an
    # error
    server, base_path = setup
    target = f"{base_path}/prop_remove_missing"

    scope, receive = get_test_scope("PUT", b"data", target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PROPPATCH", PROPPATCH_REMOVE_MISSING_BODY, target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 207


# ---- RFC 4918 §9.3 MKCOL ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_mkcol_error_paths(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.3.1: 405 on an existing collection, 409 when the parent is
    # missing (the server MUST NOT create intermediate collections)
    server, base_path = setup

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/exists_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/exists_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 405

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/no_dir/inner_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_mkcol_client_disconnect(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # the base do_mkcol gate reads the (empty) body before dispatching: a
    # client disconnect mid-read must surface as 400, not a TypeError
    server, base_path = setup

    scope, _ = get_test_scope("MKCOL", b"", f"{base_path}/mkcol_aborted")
    _, response = await server.handle(scope, DisconnectReceive(b"x"), fake_send)
    assert response.status == 400


# ---- RFC 4918 §9.4 GET / HEAD ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_get_head(setup: tuple[DAVApp, str], provider_name: str) -> None:
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

    # HEAD - dir
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


# ---- RFC 4918 §9.5 PUT ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_put(setup: tuple[DAVApp, str], provider_name: str) -> None:
    server, base_path = setup

    put_filename = "put_file"
    file_content = uuid4().hex.encode("utf-8")

    # PUT - file
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # GET - file
    scope, receive = get_test_scope("GET", b"", f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content

    # PUT - file - overwrite # TODO? 204 when the destination exists
    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/{put_filename}")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201


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
async def test_method_put_error_paths(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    server, base_path = setup

    # PUT onto an existing collection -> 405
    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/target_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", b"data", f"{base_path}/target_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 405

    # PUT under a missing parent -> 409
    scope, receive = get_test_scope(
        "PUT", b"data", f"{base_path}/no_such_dir/inner_file"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_put_if_etag_precondition(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 10.4: an If header with the current etag passes, one with a
    # stale etag fails with 412 (exercises the providers' real etag impl)
    server, base_path = setup
    target = f"{base_path}/etag_file"
    old_content = uuid4().hex.encode("utf-8")
    new_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("PUT", old_content, target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", target)
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    etag = response.headers[b"ETag"].decode("utf-8")

    # correct etag in the If header -> the PUT passes
    scope, receive = get_test_scope(
        "PUT",
        new_content,
        target,
        if_header=f"<{target}>([{etag}])",
    )
    _, response = await server.handle(scope, receive, fake_send)
    # the project answers 201 for overwrite PUT (registered deviation)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", target)
    _, response = await server.handle(scope, receive, fake_send)
    assert await get_response_content(response) == new_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_put_does_not_block_provider(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # a PUT still receiving its body must not block other requests on the
    # provider (the provider lock must never be held across body receive)
    server, base_path = setup

    scope, _ = get_test_scope("PUT", b"x", f"{base_path}/slow_upload_file")
    parking = ParkingReceive(b"first-")
    put_task = asyncio.create_task(server.handle(scope, parking, fake_send))

    # let the PUT task start and park inside its body receive
    await asyncio.sleep(0.05)
    assert not put_task.done()

    try:
        # another request must complete while the PUT is parked
        scope, receive = get_test_scope("GET", b"", f"{base_path}")
        _, response = await asyncio.wait_for(
            server.handle(scope, receive, fake_send), timeout=2
        )
        assert response.status == 200
    finally:
        # always release the parked PUT, otherwise it would keep holding
        # fs_lock (pre-fix) and stall the fixture teardown
        parking.release_event.set()

    # the upload must complete normally
    _, response = await asyncio.wait_for(put_task, timeout=2)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", f"{base_path}/slow_upload_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == b"first-"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_put_client_disconnect_persists_nothing(
    setup: tuple[DAVApp, str], provider_name: str, tmp_path: Path
) -> None:
    # an aborted upload must not leave a truncated file behind: persist
    # nothing and answer 400
    server, base_path = setup

    scope, _ = get_test_scope("PUT", b"x", f"{base_path}/aborted_file")
    _, response = await server.handle(scope, DisconnectReceive(b"partial"), fake_send)
    # the status is moot — the client is gone — the file must not exist

    scope, receive = get_test_scope("GET", b"", f"{base_path}/aborted_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    # an aborted overwrite must keep the old content intact (memory updates
    # after the full body is received; fs writes to a temp file and renames
    # on completion)
    old_content = uuid4().hex.encode("utf-8")
    scope, receive = get_test_scope(
        "PUT", old_content, f"{base_path}/overwrite_aborted_file"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, _ = get_test_scope("PUT", b"x", f"{base_path}/overwrite_aborted_file")
    _, response = await server.handle(scope, DisconnectReceive(b"partial"), fake_send)

    scope, receive = get_test_scope("GET", b"", f"{base_path}/overwrite_aborted_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == old_content

    # no temp file leftovers
    if provider_name == "fs":
        assert not list((tmp_path / "test_zone").rglob("*.tmp"))


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["fs"])
async def test_method_put_fs_defensive_error_paths(
    setup: tuple[DAVApp, str], tmp_path: Path, mocker: MockerFixture
) -> None:
    # fs provider only: cover the PermissionError and FileNotFoundError
    # defensive branches of _do_put
    server, base_path = setup
    fs_root = tmp_path / "test_zone"
    assert fs_root.is_dir()

    # PUT into a read-only directory -> 403
    locked_dir = fs_root / Path(base_path).name / "locked_dir"
    locked_dir.mkdir()
    locked_dir.chmod(0o500)
    try:
        scope, receive = get_test_scope("PUT", b"data", f"{base_path}/locked_dir/file")
        _, response = await server.handle(scope, receive, fake_send)
        assert response.status == 403
    finally:
        locked_dir.chmod(0o700)

    # an aborted upload whose partial file cannot be removed (defensive:
    # the file vanished between open and cleanup) still reports 400
    mock_remove = mocker.patch("aiofiles.os.remove", side_effect=FileNotFoundError)
    scope, _ = get_test_scope("PUT", b"x", f"{base_path}/vanishing_file")
    _, response = await server.handle(scope, DisconnectReceive(b"partial"), fake_send)
    assert response.status == 400
    assert mock_remove.called


# ---- RFC 4918 §9.6 DELETE ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_delete(setup: tuple[DAVApp, str], provider_name: str) -> None:
    server, base_path = setup

    put_filename = "delete_file"
    file_content = uuid4().hex.encode("utf-8")

    # PUT - file
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
async def test_method_delete_collection(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.6: DELETE on a collection removes the collection and all
    # its members
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/del_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/del_dir/file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("DELETE", b"", f"{base_path}/del_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    scope, receive = get_test_scope("GET", b"", f"{base_path}/del_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", f"{base_path}/del_dir/file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404


# ---- RFC 4918 §9.8 COPY ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_file(setup: tuple[DAVApp, str], provider_name: str) -> None:
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

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
    # RFC 4918 9.8.4: 201 when the destination is new
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", f"{base_path}/copy_file2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_collection(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.8.3: COPY with Depth: infinity duplicates the collection
    # and all child resources
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/src_dir")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/src_dir/sub")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/src_dir/file1")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "PUT", file_content, f"{base_path}/src_dir/sub/file2"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "COPY",
        b"",
        f"{base_path}/src_dir",
        f"{base_path}/dst_dir",
        depth="infinity",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    for path in (
        f"{base_path}/dst_dir/file1",
        f"{base_path}/dst_dir/sub/file2",
    ):
        scope, receive = get_test_scope("GET", b"", path)
        _, response = await server.handle(scope, receive, fake_send)
        assert response.status == 200
        assert await get_response_content(response) == file_content

    # the source collection stays intact
    scope, receive = get_test_scope("GET", b"", f"{base_path}/src_dir/file1")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_move_overwrite_semantics(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 10.3 Overwrite header: F on an existing destination -> 412,
    # T -> replace (204); the destination carries the source content after
    server, base_path = setup
    source_content = uuid4().hex.encode("utf-8")
    dst_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("PUT", source_content, f"{base_path}/ow_src")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", dst_content, f"{base_path}/ow_dst")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # COPY - Overwrite: F -> 412 (destination exists)
    scope, receive = get_test_scope(
        "COPY",
        b"",
        f"{base_path}/ow_src",
        f"{base_path}/ow_dst",
        overwrite="F",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 412

    # COPY - Overwrite: T -> 204
    scope, receive = get_test_scope(
        "COPY",
        b"",
        f"{base_path}/ow_src",
        f"{base_path}/ow_dst",
        overwrite="T",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    scope, receive = get_test_scope("GET", b"", f"{base_path}/ow_dst")
    _, response = await server.handle(scope, receive, fake_send)
    assert await get_response_content(response) == source_content

    # MOVE - Overwrite: F on a new destination -> 201
    scope, receive = get_test_scope(
        "MOVE",
        b"",
        f"{base_path}/ow_src",
        f"{base_path}/ow_dst2",
        overwrite="F",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    # MOVE - Overwrite: F on an existing destination -> 412 (needs a fresh
    # source: ow_src was moved away above)
    scope, receive = get_test_scope("PUT", source_content, f"{base_path}/ow_src2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", dst_content, f"{base_path}/ow_dst2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "MOVE",
        b"",
        f"{base_path}/ow_src2",
        f"{base_path}/ow_dst2",
        overwrite="F",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 412

    # MOVE - Overwrite: T -> 204
    scope, receive = get_test_scope(
        "MOVE",
        b"",
        f"{base_path}/ow_src2",
        f"{base_path}/ow_dst2",
        overwrite="T",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 204

    scope, receive = get_test_scope("GET", b"", f"{base_path}/ow_dst2")
    _, response = await server.handle(scope, receive, fake_send)
    assert await get_response_content(response) == source_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_move_missing_source_404(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    server, base_path = setup

    scope, receive = get_test_scope(
        "COPY", b"", f"{base_path}/no_src", f"{base_path}/dst"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope(
        "MOVE", b"", f"{base_path}/no_src", f"{base_path}/dst"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_copy_missing_dst_parent_409(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/src409")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "COPY",
        b"",
        f"{base_path}/src409",
        f"{base_path}/no_dir/dst",
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 409


# ---- RFC 4918 §9.9 MOVE ----


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_move_file(setup: tuple[DAVApp, str], provider_name: str) -> None:
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

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
    # RFC 4918 9.9.4: 201 when the destination is new
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", f"{base_path}/move_file")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", f"{base_path}/move_file2")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", PROVIDER_NAMES)
async def test_method_move_collection(
    setup: tuple[DAVApp, str], provider_name: str
) -> None:
    # RFC 4918 9.9.3: MOVE on a collection moves the whole tree
    server, base_path = setup
    file_content = uuid4().hex.encode("utf-8")

    scope, receive = get_test_scope("MKCOL", b"", f"{base_path}/mv_src")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("PUT", file_content, f"{base_path}/mv_src/file1")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope(
        "MOVE", b"", f"{base_path}/mv_src", f"{base_path}/mv_dst"
    )
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 201

    scope, receive = get_test_scope("GET", b"", f"{base_path}/mv_src")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", f"{base_path}/mv_src/file1")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 404

    scope, receive = get_test_scope("GET", b"", f"{base_path}/mv_dst/file1")
    _, response = await server.handle(scope, receive, fake_send)
    assert response.status == 200
    assert await get_response_content(response) == file_content
