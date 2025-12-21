import pytest

from asgi_webdav.config import get_global_config
from asgi_webdav.constants import AppEntryParameters
from asgi_webdav.exception import DAVException
from asgi_webdav.helpers import (
    detect_charset,
    get_dict_from_xml,
    guess_type,
    is_browser_user_agent,
    paser_timezone_key,
)
from asgi_webdav.response import get_response_body_generator

from .testkit_common import (
    CLIENT_UA_CHROME,
    CLIENT_UA_FIREFOX,
    CLIENT_UA_MACOS_FINDER,
    CLIENT_UA_SAFARI,
    CLIENT_UA_WINDOWS_EXPLORER,
)


def test_guess_type():
    config = get_global_config()
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
async def test_detect_charset(tmp_path):
    for encoding, content in detect_charset_content.items():
        file_path = tmp_path / f"charset-{encoding}.txt"
        file_path.write_text(content, encoding=encoding)

    charset = await detect_charset(tmp_path / "charset-utf-8.txt", None)
    assert charset is None

    charset = await detect_charset(tmp_path / "charset-utf-8.txt", "bad/xxx")
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
        CLIENT_UA_FIREFOX,
        CLIENT_UA_SAFARI,
        CLIENT_UA_CHROME,
    ]

    browser_user_agent_data_bytes = [
        CLIENT_UA_FIREFOX.encode(),
        CLIENT_UA_SAFARI.encode(),
        CLIENT_UA_CHROME.encode(),
    ]
    other_user_agent_data = [
        None,
        b"",
        CLIENT_UA_MACOS_FINDER,
        CLIENT_UA_WINDOWS_EXPLORER,
    ]

    for user_agent in browser_user_agent_data:
        assert is_browser_user_agent(user_agent)

    for user_agent in browser_user_agent_data_bytes:
        assert is_browser_user_agent(user_agent)

    for user_agent in other_user_agent_data:
        assert not is_browser_user_agent(user_agent)


@pytest.mark.asyncio
async def test_func_get_response_body_generator():
    test_line = b"1234567890"
    test_block_size = 20
    data = b""
    while len(data) < test_block_size * 10:
        data += test_line

    # default
    data_new = b""
    async for data_block, _ in get_response_body_generator(
        data, block_size=test_block_size
    ):
        data_new += data_block
    assert data == data_new

    # start-
    data_new = b""
    async for data_block, _ in get_response_body_generator(
        data, content_range_start=0, block_size=test_block_size
    ):
        data_new += data_block
    assert data == data_new

    # start-end
    data_new = b""
    async for data_block, _ in get_response_body_generator(
        data, content_range_start=0, content_range_end=100, block_size=test_block_size
    ):
        data_new += data_block
    assert len(data_new) == 100


def test_get_dav_property_data_from_xml():
    # all good
    assert get_dict_from_xml(
        data=b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><random xmlns="http://webdav.org/neon/litmus/">foobar</random></D:prop></D:set>\n</D:propertyupdate>\n',
        propert_type="propertyupdate",
    ) == {
        "@xmlns": {"D": "DAV:"},
        "DAV::set": {
            "DAV::prop": {
                "http://webdav.org/neon/litmus/:random": {
                    "@xmlns": {"": "http://webdav.org/neon/litmus/"},
                    "#text": "foobar",
                }
            }
        },
    }

    # bad
    assert get_dict_from_xml(data=b"", propert_type="propertyupdate") == {}

    assert (
        get_dict_from_xml(
            data=b'<?xml version="1.0" encoding="utf-8" ?>\n<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop><random xmlns="http://webdav.org/neon/litmus/">foobar</random></D:prop></D:set>\n</D:propertyupdate>\n',
            propert_type="bad",
        )
        == {}
    )


def test_get_timezone_from_env():
    assert paser_timezone_key("Asia/Shanghai") == "Asia/Shanghai"

    with pytest.raises(DAVException):
        paser_timezone_key("Invalid/TimeZone")
