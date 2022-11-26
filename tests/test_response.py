import re

import pytest

from asgi_webdav.config import Config, init_config_from_obj
from asgi_webdav.constants import (
    CLIENT_USER_AGENT_RE_CHROME,
    CLIENT_USER_AGENT_RE_FIREFOX,
    CLIENT_USER_AGENT_RE_MACOS_FINDER,
    CLIENT_USER_AGENT_RE_SAFARI,
    CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER,
    HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV,
    HIDE_FILE_IN_DIR_RULE_MACOS,
)
from asgi_webdav.response import DAVHideFileInDir, DAVResponse


def test_can_be_compressed():
    assert DAVResponse.can_be_compressed("text/plain", "")
    assert DAVResponse.can_be_compressed("text/html; charset=utf-8", "")
    assert DAVResponse.can_be_compressed("dont/compress", "") is False

    assert DAVResponse.can_be_compressed("compress/please", "compress")
    assert DAVResponse.can_be_compressed("compress/please", "decompress") is False


FIREFOX_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:107.0) Gecko/20100101 Firefox/107.0"
SAFARI_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15"
CHROME_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
MACOS_FINDER_UA = "WebDAVFS/3.0.0 (03008000) Darwin/21.3.0 (x86_64)"
WINDOWS_EXPLORER_UA = "Microsoft-WebDAV-MiniRedir/10.0.19043"


def test_user_agent_regex():
    data = {
        FIREFOX_UA: CLIENT_USER_AGENT_RE_FIREFOX,
        SAFARI_UA: CLIENT_USER_AGENT_RE_SAFARI,
        CHROME_UA: CLIENT_USER_AGENT_RE_CHROME,
        MACOS_FINDER_UA: CLIENT_USER_AGENT_RE_MACOS_FINDER,
        WINDOWS_EXPLORER_UA: CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER,
    }

    for ua in data.keys():
        for regex in data.values():
            print(regex, ua)
            if data[ua] == regex:
                assert re.match(regex, ua) is not None

            else:
                assert re.match(regex, ua) is None


def test_hide_file_in_dir_rule():
    assert re.match(HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV, "aa.WebDAV") is not None
    assert re.match(HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV, ".WebDAV") is None

    assert re.match(HIDE_FILE_IN_DIR_RULE_MACOS, "._file") is not None
    assert re.match(HIDE_FILE_IN_DIR_RULE_MACOS, "._") is None


@pytest.mark.asyncio
async def test_hide_file_in_dir_default_rules():
    hide_file_in_dir = DAVHideFileInDir(Config())

    # Common
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "aa.WebDAV"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        WINDOWS_EXPLORER_UA, "aa.WebDAV"
    )

    # hit skipped ua in cache
    assert await hide_file_in_dir.is_match_hide_file_in_dir(FIREFOX_UA, "aa.WebDAV")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(FIREFOX_UA, "aa.WebDAV")

    # macOS
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "Thumbs.db"
    )

    # Windows
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        WINDOWS_EXPLORER_UA, ".DS_Store"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        WINDOWS_EXPLORER_UA, "._test"
    )

    # Synology
    assert await hide_file_in_dir.is_match_hide_file_in_dir(MACOS_FINDER_UA, "#recycle")
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        WINDOWS_EXPLORER_UA, "@eaDir"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_default_rules():
    hide_file_in_dir = DAVHideFileInDir(
        init_config_from_obj(
            {
                "hide_file_in_dir": {"enable_default_rules": False},
            }
        )
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "aa.WebDAV"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "Thumbs.db"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_all():
    hide_file_in_dir = DAVHideFileInDir(
        init_config_from_obj(
            {
                "hide_file_in_dir": {"enable": False},
            }
        )
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "aa.WebDAV"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "Thumbs.db"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_user_rules():
    hide_file_in_dir = DAVHideFileInDir(
        init_config_from_obj(
            {
                "hide_file_in_dir": {
                    "user_rules": {"": r".+\.hide$", "AnOtherClient": r"^hide.*"}
                },
            }
        )
    )

    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "file.hide"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        MACOS_FINDER_UA, "file.display"
    )
