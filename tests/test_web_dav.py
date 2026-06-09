import tempfile
from pathlib import Path
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
from asgi_webdav.web_dav import WebDAV, load_templates


def _make_config() -> MagicMock:
    config = MagicMock()
    config.enable_dir_browser = True
    config.provider_mapping = []
    config.dir_browser_dir = None
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


class TestLoadTemplates:
    def test_loads_bundled_templates(self):
        templates = load_templates()
        assert all(
            name in templates
            for name in (
                "index.html",
                "row_parent.html",
                "row_directory.html",
                "row_file.html",
            )
        )
        assert all(t is not None for t in templates.values())

    def test_bundled_templates_are_valid(self):
        templates = load_templates()
        result = templates["row_file.html"].substitute(
            href="/test.txt",
            name="test.txt",
            type="text/plain",
            size="100",
            modified="2025-01-01",
        )
        assert "/test.txt" in result
        assert "test.txt" in result
        assert "text/plain" in result
        assert "100" in result

    def test_bundled_row_directory_template(self):
        templates = load_templates()
        result = templates["row_directory.html"].substitute(
            href="/mydir", name="mydir", type="application/index", modified="2025-01-01"
        )
        assert "/mydir" in result
        assert "mydir" in result
        assert "<b>" in result

    def test_bundled_row_parent_template(self):
        templates = load_templates()
        result = templates["row_parent.html"].substitute(href="/parent")
        assert "/parent" in result
        assert ".." in result

    def test_custom_dir_overrides_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_index = Path(tmpdir) / "index.html"
            custom_index.write_text("CUSTOM INDEX ${path}")

            templates = load_templates(tmpdir)
            result = templates["index.html"].substitute(path="/test")
            assert result == "CUSTOM INDEX /test"

            assert templates["row_file.html"] is not None
            result = templates["row_file.html"].substitute(
                href="/f", name="f", type="t", size="1", modified="m"
            )
            assert "<tr>" in result

    def test_custom_dir_partial_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_row_file = Path(tmpdir) / "row_file.html"
            custom_row_file.write_text("<tr><td>FILE: ${name}</td></tr>")

            templates = load_templates(tmpdir)
            result = templates["row_file.html"].substitute(
                href="/f", name="myfile.txt", type="t", size="1", modified="m"
            )
            assert "FILE: myfile.txt" in result

            result = templates["row_directory.html"].substitute(
                href="/d", name="mydir", type="t", modified="m"
            )
            assert "<b>" in result


@pytest.mark.asyncio
async def test_create_dir_browser_content_html_structure(webdav):
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
    assert 'href="/_/static/styles.css"' in html
    assert "<thead>" in html
    assert "<tbody>" in html
    assert 'class="align-right"' in html
    assert "ASGI WebDAV" in html

    dir_idx = html.index("dir_a")
    file_idx = html.index("file_b.txt")
    assert dir_idx < file_idx

    assert "<b>dir_a</b>" in html
    assert ">file_b.txt</a>" in html
    assert ">100<" in html or ">1,000<" in html or "100</td>" in html
