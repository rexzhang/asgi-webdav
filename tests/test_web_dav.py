from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from asgi_webdav.config import Provider
from asgi_webdav.constants import DAVPath
from asgi_webdav.exceptions import DAVExceptionProviderInitFailed
from asgi_webdav.property import DAVProperty
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.provider.webhdfs import WebHDFSProvider
from asgi_webdav.web_dav import WebDAV


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


@pytest.mark.asyncio
async def test_create_dir_browser_content():

    config = MagicMock()
    config.enable_dir_browser = True

    webdav = WebDAV(config)

    webdav.timezone = ZoneInfo("UTC")

    webdav._hide_file_in_dir = MagicMock()
    webdav._hide_file_in_dir.is_match_hide_file_in_dir = AsyncMock(return_value=False)

    template = MagicMock()
    template.render.return_value = "<html>OK</html>"

    webdav.templates = MagicMock()
    webdav.templates.get_template.return_value = template

    root = DAVPath("/")

    prop_file = MagicMock(spec=DAVProperty)
    prop_file.basic_data.display_name = "b_file"
    prop_file.basic_data.content_type = "text/plain"
    prop_file.basic_data.content_length = 10
    prop_file.basic_data.is_collection = False
    prop_file.basic_data.last_modified.display.return_value = "2024"

    prop_dir = MagicMock(spec=DAVProperty)
    prop_dir.basic_data.display_name = "a_dir"
    prop_dir.basic_data.content_type = "inode/directory"
    prop_dir.basic_data.content_length = 0
    prop_dir.basic_data.is_collection = True
    prop_dir.basic_data.last_modified.display.return_value = "2024"

    dav_properties = {
        DAVPath("/a"): prop_dir,
        DAVPath("/b"): prop_file,
        DAVPath("/"): prop_file,
    }

    result = await webdav._create_dir_browser_content(
        client_user_agent="Mozilla/5.0",
        root_path=root,
        dav_properties=dav_properties,
    )

    assert isinstance(result, bytes)

    webdav.templates.get_template.assert_called_once_with("dir_browser.html")
    template.render.assert_called_once()

    args = template.render.call_args.kwargs

    assert args["path"] == "/"
    assert args["parent"] is None

    assert len(args["items"]) == 2

    assert args["items"][0]["is_dir"] is True
    assert args["items"][0]["name"] == "a_dir"

    assert args["items"][1]["is_dir"] is False
    assert args["items"][1]["name"] == "b_file"
