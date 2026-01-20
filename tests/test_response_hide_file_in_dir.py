import re

import pytest

from asgi_webdav.config import Config, generate_config_from_dict
from asgi_webdav.constants import (
    CLIENT_USER_AGENT_RE_CHROME,
    CLIENT_USER_AGENT_RE_FIREFOX,
    CLIENT_USER_AGENT_RE_MACOS_FINDER,
    CLIENT_USER_AGENT_RE_SAFARI,
    CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER,
    HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV,
    HIDE_FILE_IN_DIR_RULE_MACOS,
)
from asgi_webdav.response import DAVHideFileInDir

from .kits.common import (
    CLIENT_UA_CHROME,
    CLIENT_UA_FIREFOX,
    CLIENT_UA_MACOS_FINDER,
    CLIENT_UA_SAFARI,
    CLIENT_UA_WINDOWS_EXPLORER,
)


def test_user_agent_regex():
    data = {
        CLIENT_UA_FIREFOX: CLIENT_USER_AGENT_RE_FIREFOX,
        CLIENT_UA_SAFARI: CLIENT_USER_AGENT_RE_SAFARI,
        CLIENT_UA_CHROME: CLIENT_USER_AGENT_RE_CHROME,
        CLIENT_UA_MACOS_FINDER: CLIENT_USER_AGENT_RE_MACOS_FINDER,
        CLIENT_UA_WINDOWS_EXPLORER: CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER,
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
        CLIENT_UA_MACOS_FINDER, "aa.WebDAV"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_WINDOWS_EXPLORER, "aa.WebDAV"
    )

    # hit skipped ua in cache
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_FIREFOX, "aa.WebDAV"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_FIREFOX, "aa.WebDAV"
    )

    # macOS
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "Thumbs.db"
    )

    # Windows
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_WINDOWS_EXPLORER, ".DS_Store"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_WINDOWS_EXPLORER, "._test"
    )

    # Synology
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "#recycle"
    )
    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_WINDOWS_EXPLORER, "@eaDir"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_default_rules():
    config = generate_config_from_dict(
        {
            "hide_file_in_dir": {"enable_default_rules": False},
        }
    )
    hide_file_in_dir = DAVHideFileInDir(config)
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "aa.WebDAV"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "Thumbs.db"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_disable_all():
    config = generate_config_from_dict(
        {
            "hide_file_in_dir": {"enable": False},
        }
    )
    hide_file_in_dir = DAVHideFileInDir(config)
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "aa.WebDAV"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "Thumbs.db"
    )


@pytest.mark.asyncio
async def test_hide_file_in_dir_user_rules():
    config = generate_config_from_dict(
        {
            "hide_file_in_dir": {
                "user_rules": {"": r".+\.hide$", "AnOtherClient": r"^hide.*"}
            },
        }
    )
    hide_file_in_dir = DAVHideFileInDir(config)

    assert await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "file.hide"
    )
    assert not await hide_file_in_dir.is_match_hide_file_in_dir(
        CLIENT_UA_MACOS_FINDER, "file.display"
    )
