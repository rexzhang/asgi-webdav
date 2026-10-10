from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from asgiref.typing import ASGIReceiveEvent, ASGISendEvent, HTTPScope
from pytest_mock import MockerFixture

from asgi_webdav.config import Provider, generate_config_from_dict
from asgi_webdav.constants import (
    DAVPath,
    DAVRangeType,
    DAVResponseContentRange,
)
from asgi_webdav.exceptions import DAVException, DAVExceptionProviderInitFailed
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse
from asgi_webdav.server import DAVApp
from asgi_webdav.web_dav import PrefixProviderInfo, WebDAV

from .kits.asgi import (
    create_asgiref_http_scope_object,
    create_dav_request_object,
)
from .kits.common import CLIENT_UA_FIREFOX

USERNAME = "username"
PASSWORD = "password"

BASIC_AUTHORIZATION = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="
ADMIN_AUTHORIZATION = "Basic YWRtaW46YWRtaW4="  # admin:admin

LOCK_BODY = (
    b'<?xml version="1.0" encoding="utf-8" ?>'
    b'<D:lockinfo xmlns:D="DAV:">'
    b"<D:lockscope><D:exclusive/></D:lockscope>"
    b"<D:locktype><D:write/></D:locktype>"
    b"<D:owner>owner</D:owner>"
    b"</D:lockinfo>"
)


@pytest.fixture(autouse=True)
def clean_prefix_provider_mapping() -> Iterator[None]:
    # WebDAV.prefix_provider_mapping is a shared class-level list: every
    # DAVApp/WebDAV built anywhere appends to it, so reset it around each test
    WebDAV.prefix_provider_mapping.clear()
    yield
    WebDAV.prefix_provider_mapping.clear()


class BodyReceive:
    """ASGI receive callable: the body in one event, http.disconnect after."""

    def __init__(self, body: bytes) -> None:
        self._body: bytes | None = body

    async def __call__(self) -> ASGIReceiveEvent:
        if self._body is not None:
            body, self._body = self._body, None
            event: ASGIReceiveEvent = {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
            return event

        # keep the disconnect watcher from spinning on immediate events
        return {"type": "http.disconnect"}


async def fake_send(event: ASGISendEvent) -> None:
    return None


def get_scope(
    method: str, path: str, headers: dict[str, str] | None = None
) -> HTTPScope:
    data = {
        "authorization": BASIC_AUTHORIZATION,
        "user-agent": "pytest",
    }
    if headers is not None:
        data.update(headers)

    return create_asgiref_http_scope_object(method=method, path=path, headers=data)


def get_dav_app(
    provider_mapping: list[dict[str, str]] | None = None,
    permissions: list[str] | None = None,
    account_mapping: list[dict[str, Any]] | None = None,
) -> DAVApp:
    if account_mapping is None:
        account_mapping = [
            {
                "username": USERNAME,
                "password": PASSWORD,
                "permissions": permissions if permissions is not None else ["+"],
            },
        ]

    config_object: dict[str, Any] = {
        "account_mapping": account_mapping,
        "provider_mapping": (
            provider_mapping
            if provider_mapping is not None
            else [{"prefix": "/", "uri": "memory:///"}]
        ),
    }
    return DAVApp(generate_config_from_dict(config_object))


async def handle_request(
    dav_app: DAVApp,
    method: str,
    path: str,
    data: bytes = b"",
    headers: dict[str, str] | None = None,
) -> DAVResponse:
    scope = get_scope(method, path, headers)
    _, response = await dav_app.handle(scope, BodyReceive(data), fake_send)
    return response


async def get_response_content(response: DAVResponse) -> bytes:
    content = b""
    async for data, _more_data in response.content_body_generator:
        content += data

    return content


def test_match_provider_class() -> None:
    assert (
        WebDAV.match_provider_class(Provider("/fs", "file:///tmp"))
        == FileSystemProvider
    )
    assert (
        WebDAV.match_provider_class(Provider("/memory", "memory:///")) == MemoryProvider
    )

    with pytest.raises(DAVExceptionProviderInitFailed):
        WebDAV.match_provider_class(Provider("/wrong_provider", "wrong_provider:///"))

    assert (
        WebDAV.match_provider_class(
            Provider("/webhdfs", "http://localhost:9870/webhdfs/v1", type="webhdfs")
        )
        == WebHDFSProvider
    )

    with pytest.raises(DAVExceptionProviderInitFailed):
        WebDAV.match_provider_class(
            Provider(
                "/wrong_http_provider",
                "http://localhost:9870/webhdfs/v1",
                type="wrong_http_provider",
            )
        )


def test_prefix_provider_info_str() -> None:
    provider = MemoryProvider(
        config=generate_config_from_dict({}),
        prefix=DAVPath("/"),
        uri="memory:///",
        home_dir=False,
        read_only=True,
        ignore_property_extra=False,
    )

    ppi = PrefixProviderInfo(
        prefix=DAVPath("/"),
        prefix_weight=1,
        provider=provider,
        home_dir=False,
        read_only=True,
        ignore_property_extra=False,
    )
    assert "read_only" in str(ppi)
    assert "home_dir" not in str(ppi)
    assert "ignore_property_extra" not in str(ppi)

    ppi = PrefixProviderInfo(
        prefix=DAVPath("/"),
        prefix_weight=1,
        provider=provider,
        home_dir=True,
        read_only=True,
        ignore_property_extra=True,
    )
    for flag in ("home_dir", "read_only", "ignore_property_extra"):
        assert flag in str(ppi)


def test_webdav_init_skips_failed_providers(tmp_path: Path) -> None:
    config = generate_config_from_dict(
        {
            "provider_mapping": [
                # unknown scheme: match_provider_class raises => skipped
                {"prefix": "/bad", "uri": "bad:///"},
                # file root does not exist: provider ctor raises => skipped
                {"prefix": "/fs", "uri": f"file://{tmp_path / 'missing'}"},
                # ok
                {"prefix": "/", "uri": "memory:///"},
            ],
        }
    )
    webdav = WebDAV(config)

    assert len(webdav.prefix_provider_mapping) == 1
    assert webdav.prefix_provider_mapping[0].prefix == DAVPath("/")


def test_webdav_init_timezone_exception(mocker: MockerFixture) -> None:
    # get_timezone() never raises DAVException in reality (it falls back to
    # UTC itself); simulate the failure to reach the defensive branch.
    # Note: that branch builds a DAVException without raising it, so the
    # timezone attribute is left unset.
    mocker.patch(
        "asgi_webdav.web_dav.get_timezone",
        side_effect=DAVException("bad TZ"),
    )

    config = generate_config_from_dict(
        {"provider_mapping": [{"prefix": "/", "uri": "memory:///"}]}
    )
    webdav = WebDAV(config)

    with pytest.raises(AttributeError):
        webdav.timezone


async def test_match_provider_none_and_distribute_404() -> None:
    dav_app = get_dav_app(provider_mapping=[{"prefix": "/a", "uri": "memory:///"}])
    webdav = dav_app.web_dav

    request = create_dav_request_object(method="GET", path="/b")
    assert webdav.match_provider(request) is None

    response = await handle_request(dav_app, "GET", "/b")
    assert response.status == 404
    content = await get_response_content(response)
    assert b"[/b]" in content


async def test_distribute_proppatch() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"12345")
    assert response.status == 201

    # empty body => propertyupdate parse failed => 400
    response = await handle_request(dav_app, "PROPPATCH", "/file")
    assert response.status == 400


async def test_distribute_lock() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"12345")
    assert response.status == 201

    response = await handle_request(dav_app, "LOCK", "/file", data=LOCK_BODY)
    assert response.status == 201
    assert response.headers[b"Lock-Token"].startswith(b"opaquelocktoken:")
    assert b"lockdiscovery" in await get_response_content(response)


async def test_distribute_unlock_unknown_token() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"12345")
    assert response.status == 201

    headers = {"lock-token": f"<opaquelocktoken:{uuid4()}>"}
    response = await handle_request(dav_app, "UNLOCK", "/file", headers=headers)
    assert response.status == 403


async def test_distribute_options() -> None:
    dav_app = get_dav_app()

    response = await handle_request(dav_app, "OPTIONS", "/")
    assert response.status == 200
    assert response.headers[b"DAV"] == b"1, 2"
    assert b"PUT" in response.headers[b"Allow"]


async def test_distribute_head_delete_move() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"12345")
    assert response.status == 201

    # HEAD
    response = await handle_request(dav_app, "HEAD", "/file")
    assert response.status == 200

    # MOVE
    response = await handle_request(
        dav_app, "MOVE", "/file", headers={"destination": "/file2"}
    )
    assert response.status == 204

    # DELETE
    response = await handle_request(dav_app, "DELETE", "/file2")
    assert response.status == 204
    response = await handle_request(dav_app, "DELETE", "/file2")
    assert response.status == 404


async def test_distribute_permission_denied_403() -> None:
    # a logged-in (non-anonymous) user gets 403 outside its permissions
    dav_app = get_dav_app(permissions=["+^/pub"])

    response = await handle_request(dav_app, "GET", "/priv")
    assert response.status == 403


async def test_distribute_unknown_method_405() -> None:
    dav_app = get_dav_app()

    # unknown verbs map to DAVMethod.UNKNOWN, which no provider implements
    response = await handle_request(dav_app, "TRACE", "/")
    assert response.status == 405
    assert b"method:UNKNOWN" in await get_response_content(response)


def test_get_depth_1_child_provider() -> None:
    config = generate_config_from_dict(
        {
            "provider_mapping": [
                {"prefix": "/", "uri": "memory:///"},
                {"prefix": "/a/b", "uri": "memory:///"},
                {"prefix": "/a/c/d", "uri": "memory:///"},
                {"prefix": "/a/e", "uri": "memory:///"},
            ],
        }
    )
    webdav = WebDAV(config)

    providers = webdav.get_depth_1_child_provider(DAVPath("/a"))
    assert {p.prefix for p in providers} == {DAVPath("/a/b"), DAVPath("/a/e")}

    assert webdav.get_depth_1_child_provider(DAVPath("/")) == []


async def test_do_propfind_bad_body_400() -> None:
    dav_app = get_dav_app()

    response = await handle_request(dav_app, "PROPFIND", "/", data=b"<not-xml")
    assert response.status == 400


async def test_do_propfind_not_found_404() -> None:
    dav_app = get_dav_app()

    response = await handle_request(
        dav_app, "PROPFIND", "/missing", headers={"depth": "0"}
    )
    assert response.status == 404


async def test_do_propfind_depth0_207() -> None:
    dav_app = get_dav_app()

    response = await handle_request(dav_app, "PROPFIND", "/", headers={"depth": "0"})
    assert response.status == 207
    assert response.headers[b"Content-Type"] == b"application/xml"
    assert b"<D:href>/</D:href>" in await get_response_content(response)


async def test_do_propfind_depth1_child_merge_and_hide() -> None:
    dav_app = get_dav_app(
        provider_mapping=[
            {"prefix": "/", "uri": "memory:///"},
            {"prefix": "/child", "uri": "memory:///"},
            {"prefix": "/child/deep", "uri": "memory:///"},
        ]
    )
    for method, path in [
        ("PUT", "/file.WebDAV"),
        ("PUT", "/open.txt"),
        ("PUT", "/child/file.txt"),
        ("MKCOL", "/sub"),
    ]:
        # MKCOL with a request body would be answered with 415 (RFC 4918)
        data = b"" if method == "MKCOL" else b"12345"
        response = await handle_request(dav_app, method, path, data=data)
        assert response.status == 201

    # depth 1: base children + the depth-1 child provider /child itself;
    # /child/deep is two levels below and must not be merged
    response = await handle_request(dav_app, "PROPFIND", "/", headers={"depth": "1"})
    assert response.status == 207
    content = await get_response_content(response)
    assert b"/open.txt" in content
    assert b"/sub" in content
    assert b">/child<" in content
    assert b"deep" not in content
    # hidden by the default rule even for an unknown user agent
    assert b"file.WebDAV" not in content

    # depth infinity: the child provider request is downgraded to depth 1,
    # so the content of the child provider is merged instead of its node
    response = await handle_request(
        dav_app, "PROPFIND", "/", headers={"depth": "infinity"}
    )
    assert response.status == 207
    content = await get_response_content(response)
    assert b"/open.txt" in content
    assert b"/child/file.txt" in content


async def test_do_propfind_permission_filter() -> None:
    dav_app = get_dav_app(
        provider_mapping=[
            {"prefix": "/", "uri": "memory:///"},
            {"prefix": "/pub2", "uri": "memory:///"},
            {"prefix": "/priv2", "uri": "memory:///"},
        ],
        account_mapping=[
            {"username": "admin", "password": "admin", "permissions": ["+"]},
            {
                "username": USERNAME,
                "password": PASSWORD,
                "permissions": ["+^/", "-^/priv", "-^/priv2"],
            },
        ],
    )

    # admin builds the tree: a denied path can not be created through the
    # restricted account itself
    admin_headers = {"authorization": ADMIN_AUTHORIZATION}
    for method, path in [("MKCOL", "/pub"), ("MKCOL", "/priv"), ("PUT", "/priv/file")]:
        data = b"" if method == "MKCOL" else b"12345"
        response = await handle_request(
            dav_app, method, path, data=data, headers=admin_headers
        )
        assert response.status == 201

    response = await handle_request(dav_app, "PROPFIND", "/", headers={"depth": "1"})
    assert response.status == 207
    content = await get_response_content(response)
    assert b"/pub" in content
    assert b"/pub2" in content
    # denied on the base provider and on the child provider
    assert b"/priv" not in content


async def test_do_propfind_home_dir_hide(tmp_path: Path) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    user_home = home_root / USERNAME
    user_home.mkdir()
    (user_home / "visible.txt").write_bytes(b"12345")
    (user_home / "secret.WebDAV").write_bytes(b"12345")

    dav_app = get_dav_app(
        provider_mapping=[
            {"prefix": "/~", "uri": f"file://{home_root}", "home_dir": "true"},
        ]
    )

    # home_dir providers skip the permission filter and go straight to
    # the hide-file-in-dir filter
    response = await handle_request(dav_app, "PROPFIND", "/~", headers={"depth": "1"})
    assert response.status == 207
    content = await get_response_content(response)
    assert b"visible.txt" in content
    assert b"secret.WebDAV" not in content


async def test_do_get_basic_data_none_raises(mocker: MockerFixture) -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"12345")
    assert response.status == 201

    provider = dav_app.web_dav.prefix_provider_mapping[0].provider
    mocker.patch.object(provider, "do_get", return_value=(200, None, None, None))

    with pytest.raises(DAVException):
        await handle_request(dav_app, "GET", "/file")


async def test_do_get_range_206() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"a" * 100)
    assert response.status == 201

    response = await handle_request(
        dav_app, "GET", "/file", headers={"range": "bytes=0-9"}
    )
    assert response.status == 206
    assert response.content_range == DAVResponseContentRange(
        DAVRangeType.RANGE, 0, 9, 100
    )
    assert response.headers[b"Accept-Ranges"] == b"bytes"
    assert await get_response_content(response) == b"a" * 10


async def test_do_get_file_full() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "PUT", "/file", data=b"a" * 100)
    assert response.status == 201

    # without a Range header the entire file is returned
    response = await handle_request(dav_app, "GET", "/file")
    assert response.status == 200
    assert response.content_length == 100
    assert await get_response_content(response) == b"a" * 100


async def test_do_get_file_not_found_404() -> None:
    dav_app = get_dav_app()

    response = await handle_request(dav_app, "GET", "/missing")
    assert response.status == 404


def _get_dav_app_for_provider_kind(provider_kind: str, tmp_path: Path) -> DAVApp:
    if provider_kind == "fs":
        fs_root = tmp_path / "root"
        fs_root.mkdir()
        return get_dav_app(
            provider_mapping=[{"prefix": "/", "uri": f"file://{fs_root}"}]
        )

    return get_dav_app(provider_mapping=[{"prefix": "/", "uri": "memory:///"}])


@pytest.mark.parametrize("provider_kind", ["memory", "fs"])
async def test_do_get_if_range_mismatch_returns_200_full_file(
    provider_kind: str, tmp_path: Path
) -> None:
    dav_app = _get_dav_app_for_provider_kind(provider_kind, tmp_path)
    response = await handle_request(dav_app, "PUT", "/file", data=b"a" * 100)
    assert response.status == 201

    # a syntactically valid If-Range which never matches the file's ETag:
    # ignore the Range header, response the entire file (RFC 7233 section 3.2)
    headers = {
        "range": "bytes=0-9",
        "if-range": 'W/"00000000000000000000000000000000"',
    }
    response = await handle_request(dav_app, "GET", "/file", headers=headers)

    assert response.status == 200
    assert response.content_length == 100
    assert b"Content-Range" not in response.headers
    assert await get_response_content(response) == b"a" * 100


@pytest.mark.parametrize("provider_kind", ["memory", "fs"])
async def test_do_get_range_not_satisfiable_returns_416(
    provider_kind: str, tmp_path: Path
) -> None:
    dav_app = _get_dav_app_for_provider_kind(provider_kind, tmp_path)
    response = await handle_request(dav_app, "PUT", "/file", data=b"a" * 100)
    assert response.status == 201

    response = await handle_request(
        dav_app, "GET", "/file", headers={"range": "bytes=500-600"}
    )

    assert response.status == 416
    assert response.headers[b"Content-Range"] == b"*/100"


@pytest.mark.parametrize("provider_kind", ["memory", "fs"])
async def test_do_get_if_range_match_returns_206(
    provider_kind: str, tmp_path: Path
) -> None:
    dav_app = _get_dav_app_for_provider_kind(provider_kind, tmp_path)
    response = await handle_request(dav_app, "PUT", "/file", data=b"a" * 100)
    assert response.status == 201

    # fetch the current ETag, then use it as a matching If-Range validator
    response = await handle_request(dav_app, "GET", "/file")
    assert response.status == 200
    etag = response.headers[b"ETag"].decode("utf-8")

    response = await handle_request(
        dav_app,
        "GET",
        "/file",
        headers={"range": "bytes=0-9", "if-range": etag},
    )

    assert response.status == 206
    assert response.content_range == DAVResponseContentRange(
        DAVRangeType.RANGE, 0, 9, 100
    )
    assert await get_response_content(response) == b"a" * 10


async def test_do_get_dir_browser_html_root() -> None:
    dav_app = get_dav_app()
    for method, path in [
        ("MKCOL", "/sub"),
        ("PUT", "/file.txt"),
        ("PUT", "/hidden.WebDAV"),
    ]:
        data = b"" if method == "MKCOL" else b"12345"
        response = await handle_request(dav_app, method, path, data=data)
        assert response.status == 201

    response = await handle_request(
        dav_app, "GET", "/", headers={"user-agent": CLIENT_UA_FIREFOX}
    )
    assert response.status == 200
    assert response.headers[b"Content-Type"] == b"text/html"
    content = await get_response_content(response)

    assert b"Index of /" in content
    assert b"file.txt" in content
    assert b"application/index" in content
    assert b">5<" in content  # formatted content_length of file.txt
    assert b"sub" in content
    assert b"current time:" in content
    # hidden by the default rule even for an unknown user agent
    assert b"hidden.WebDAV" not in content
    # the root page has no parent link row
    assert b">..<" not in content


async def test_do_get_dir_browser_html_subdir_parent_link() -> None:
    dav_app = get_dav_app()
    response = await handle_request(dav_app, "MKCOL", "/sub")
    assert response.status == 201

    response = await handle_request(
        dav_app, "GET", "/sub", headers={"user-agent": CLIENT_UA_FIREFOX}
    )
    assert response.status == 200
    content = await get_response_content(response)
    assert b"Index of /sub" in content
    # the parent link row
    assert b">..<" in content


async def test_do_get_dir_browser_html_fs_provider(tmp_path: Path) -> None:
    # the fs provider propfind includes the requested node itself, so this
    # also exercises skipping the root row while building the page
    fs_root = tmp_path / "root"
    fs_root.mkdir()
    (fs_root / "file.txt").write_bytes(b"12345")

    dav_app = get_dav_app(
        provider_mapping=[{"prefix": "/", "uri": f"file://{fs_root}"}]
    )

    response = await handle_request(
        dav_app, "GET", "/", headers={"user-agent": CLIENT_UA_FIREFOX}
    )
    assert response.status == 200
    assert response.headers[b"Content-Type"] == b"text/html"
    content = await get_response_content(response)
    assert b"Index of /" in content
    assert b"file.txt" in content
    assert b">..<" not in content


async def test_do_get_dir_browser_html_hidden_display_name(
    mocker: MockerFixture,
) -> None:
    dav_app = get_dav_app()
    for path in ("/ok.txt", "/secret.WebDAV"):
        response = await handle_request(dav_app, "PUT", path, data=b"12345")
        assert response.status == 201

    # disable the shared propfind-level filter, so only the dir browser's
    # own hide check can drop the file from the generated page
    async def passthrough(
        request: DAVRequest, data: dict[DAVPath, DAVProperty]
    ) -> dict[DAVPath, DAVProperty]:
        return data

    mocker.patch.object(
        dav_app.web_dav, "_do_propfind_hide_file_in_dir", new=passthrough
    )

    response = await handle_request(
        dav_app, "GET", "/", headers={"user-agent": CLIENT_UA_FIREFOX}
    )
    assert response.status == 200
    content = await get_response_content(response)
    assert b"ok.txt" in content
    assert b"secret.WebDAV" not in content


async def test_do_get_dir_non_browser_ua_empty() -> None:
    dav_app = get_dav_app()

    # unknown user agent + dir browser enabled: response an empty body
    response = await handle_request(dav_app, "GET", "/")
    assert response.status == 200
    assert response.content_length == 0
