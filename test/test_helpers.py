from pathlib import Path

import pytest

from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.helpers import guess_type, detect_charset, is_browser_user_agent
from asgi_webdav.config import get_config


def test_guess_type():
    config = get_config()
    config.update_from_app_args_and_env_and_default_value(AppEntryParameters())

    content_type, encoding = guess_type(config, "README")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type(config, "test.md")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type(config, "../BuildDocker.sh")
    assert isinstance(content_type, str)


detect_charset_filename_template = "test_zone/charset-{}.txt"
detect_charset_target_encoding_list = ["utf-8", "gb2312", "gbk", "gb18030"]
detect_charset_content = {
    "utf-8": "只有民族的，才是世界的。",
    "ascii": "Only the nation's is the world's.",
}


def detect_charset_init():
    for encoding, content in detect_charset_content.items():
        filename = detect_charset_filename_template.format(encoding)
        with open(filename, "w", encoding=encoding) as fp:
            fp.write(content)
            fp.close()

    return


@pytest.mark.asyncio
async def test_detect_charset():
    detect_charset_init()

    charset = await detect_charset(
        detect_charset_filename_template.format("utf-8"), None
    )
    assert charset is None
    charset = await detect_charset(
        Path(detect_charset_filename_template.format("utf-8")), None
    )
    assert charset is None
    charset = await detect_charset(
        Path(detect_charset_filename_template.format("utf-8")), "bad/xxx"
    )
    assert charset is None

    # TODO
    # for encoding in detect_charset_content.keys():
    #     print("current encoding: {}".format(encoding))
    #     charset = await detect_charset(
    #         Path(detect_charset_filename_template.format(encoding)), text_charset
    #     )
    #     assert charset == encoding


def test_is_browser_user_agent():
    browser_user_agent_data = [
        b"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",  # firefox
        b"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.106 Safari/537.36",  # chrome
        b"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",  # safari
    ]

    other_user_agent_data = [
        None,
        b"",
        b"WebDAVFS/3.0.0 (03008000) Darwin/20.5.0 (x86_64)",  # macOS 11.4 finder
    ]

    for user_agent in browser_user_agent_data:
        assert is_browser_user_agent(user_agent)

    for user_agent in other_user_agent_data:
        assert not is_browser_user_agent(user_agent)
