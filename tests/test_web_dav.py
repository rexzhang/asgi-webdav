from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from asgi_webdav.config import Provider
from asgi_webdav.constants import DAVPath, DAVTime
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.web_dav import WebDAV


def _make_config() -> MagicMock:
    config = MagicMock()
    config.enable_dir_browser = True
    config.provider_mapping = []
    config.dir_browser_template = None
    return config


def _make_dav_property(
    path: str,
    name: str,
    is_collection: bool,
    content_type: str = "",
    content_length: int = 0,
) -> tuple[DAVPath, DAVProperty]:
    dav_path = DAVPath(path)
    prop = DAVProperty(
        href_path=dav_path,
        is_collection=is_collection,
        basic_data=DAVPropertyBasicData(
            is_collection=is_collection,
            display_name=name,
            creation_date=DAVTime(0),
            last_modified=DAVTime(0),
            content_type=content_type,
            content_length=content_length,
        ),
    )
    return dav_path, prop


@pytest.fixture
def webdav() -> WebDAV:
    wd = WebDAV(_make_config())
    wd.timezone = ZoneInfo("UTC")
    wd._hide_file_in_dir = MagicMock()
    wd._hide_file_in_dir.is_match_hide_file_in_dir = AsyncMock(return_value=False)
    return wd


def test_match_provider_class():
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


def _get_html(webdav, properties, root="/"):
    root_path = DAVPath(root)
    return webdav._create_dir_browser_content(
        client_user_agent="Mozilla/5.0",
        root_path=root_path,
        dav_properties=properties,
    )


@pytest.mark.asyncio
async def test_create_dir_browser_content_root(webdav):
    props = dict(
        [
            _make_dav_property("/", "/", True, content_type="application/index"),
            _make_dav_property(
                "/dir_a", "dir_a", True, content_type="application/index"
            ),
            _make_dav_property(
                "/file_b.txt",
                "file_b.txt",
                False,
                content_type="text/plain",
                content_length=100,
            ),
        ]
    )

    result = await _get_html(webdav, props, "/")

    html = result.decode("utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Index of" in html
    assert "/" in html
    assert "dir_a" in html
    assert "file_b.txt" in html
    assert "100" in html
    assert "text/plain" in html
    assert ".." not in html


@pytest.mark.asyncio
async def test_create_dir_browser_content_subdir(webdav):
    props = dict(
        [
            _make_dav_property("/parent", "parent", True),
            _make_dav_property("/parent/sub_a", "sub_a", True),
            _make_dav_property("/parent/file_b", "file_b", False, content_length=42),
        ]
    )

    result = await _get_html(webdav, props, "/parent")

    html = result.decode("utf-8")
    assert "sub_a" in html
    assert "file_b" in html
    assert "42" in html
    assert ".." in html
    assert "parent" in html


@pytest.mark.asyncio
async def test_create_dir_browser_content_sorting(webdav):
    props = dict(
        [
            _make_dav_property("/root", "root", True),
            _make_dav_property("/root/b_file", "b_file", False, content_length=10),
            _make_dav_property("/root/a_dir", "a_dir", True),
        ]
    )

    result = await _get_html(webdav, props, "/root")

    html = result.decode("utf-8")

    dir_idx = html.index("a_dir")
    file_idx = html.index("b_file")
    assert dir_idx < file_idx


@pytest.mark.asyncio
async def test_create_dir_browser_content_hide_file(webdav):
    webdav._hide_file_in_dir.is_match_hide_file_in_dir = AsyncMock(return_value=True)

    props = dict(
        [
            _make_dav_property("/", "/", True),
            _make_dav_property("/file.txt", "file.txt", False, content_length=10),
        ]
    )

    result = await _get_html(webdav, props, "/")

    html = result.decode("utf-8")
    assert "file.txt" not in html


@pytest.mark.asyncio
async def test_create_dir_browser_content_empty_dir(webdav):
    props = dict(
        [
            _make_dav_property("/empty", "empty", True),
        ]
    )

    result = await _get_html(webdav, props, "/empty")

    html = result.decode("utf-8")
    assert '<td class="align-right">-</td>' in html  # parent row
    assert '<td><a href="/empty"' not in html  # no rows for /empty itself
    assert "Index of" in html
