from pathlib import Path

import pytest

from asgi_webdav.helpers import guess_type, detect_charset


def test_guess_type():
    content_type, encoding = guess_type("README")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type("test.md")
    assert isinstance(content_type, str)

    content_type, encoding = guess_type("../BuildDocker.sh")
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
