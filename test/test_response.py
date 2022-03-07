import pytest

from asgi_webdav.config import Config, update_config_from_obj
from asgi_webdav.response import DAVHideFileInDir


MACOS_UA = "WebDAVFS/3.0.0 (03008000) Darwin/21.3.0 (x86_64)"
WINDOWS_UA = "Microsoft-WebDAV-MiniRedir/10.0.19043"
FIREFOX_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:97.0) Gecko/20100101 Firefox/97.0"
)


@pytest.mark.asyncio
async def test_hide_file_in_dir_default_rules():
    hide_file_in_dir = DAVHideFileInDir(Config())

    # Common
    assert await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "aa.WebDAV")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(WINDOWS_UA, "aa.WebDAV")

    # hit skipped ua in cache
    assert await hide_file_in_dir.is_match_hide_file_in_dir(FIREFOX_UA, "aa.WebDAV")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(FIREFOX_UA, "aa.WebDAV")

    # macOS
    assert await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "Thumbs.db")

    # Windows
    assert await hide_file_in_dir.is_match_hide_file_in_dir(WINDOWS_UA, ".DS_Store")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(WINDOWS_UA, "._.test")

    # Synology
    assert await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "#recycle")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(WINDOWS_UA, "@eaDir")


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_default_rules():
    hide_file_in_dir = DAVHideFileInDir(
        update_config_from_obj(
            {
                "hide_file_in_dir": {"enable_default_rules": False},
            }
        )
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "aa.WebDAV")
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "Thumbs.db")


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_all():
    hide_file_in_dir = DAVHideFileInDir(
        update_config_from_obj(
            {
                "hide_file_in_dir": {"enable": False},
            }
        )
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "aa.WebDAV")
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "Thumbs.db")


@pytest.mark.asyncio
async def test_hide_file_in_dir_user_rules():
    hide_file_in_dir = DAVHideFileInDir(
        update_config_from_obj(
            {
                "hide_file_in_dir": {
                    "user_rules": {"": r".+\.hide$", "AnOtherClient": "^hide.*"}
                },
            }
        )
    )

    assert await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_UA, "file.hide")
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_UA, "file.display"
    )
