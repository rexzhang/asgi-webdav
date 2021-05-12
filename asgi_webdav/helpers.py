from typing import Optional, Union
import hashlib
from datetime import datetime
from pathlib import Path
from mimetypes import guess_type as orig_guess_type
from collections.abc import Callable, AsyncGenerator

import aiofiles
from chardet import UniversalDetector

from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE
from asgi_webdav.config import get_config


async def send_response_in_one_call(send, status: int, message: bytes = b"") -> None:
    """moved to  DAVResponse.send_in_one_call()"""
    headers = [
        (b"Content-Type", b"text/html"),
        # (b'Content-Type', b'application/xml'),
        (b"Content-Length", bytes(str(len(message)), encoding="utf8")),
        (b"Date", bytes(datetime.utcnow().isoformat(), encoding="utf8")),
    ]
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": message,
        }
    )

    return


async def receive_all_data_in_one_call(receive: Callable) -> bytes:
    data = b""
    more_body = True
    while more_body:
        request_data = await receive()
        data += request_data.get("body", b"")
        more_body = request_data.get("more_body")

    return data


async def empty_data_generator() -> AsyncGenerator[bytes, bool]:
    yield "", False


async def get_data_generator_from_content(
    content: bytes,
) -> AsyncGenerator[bytes, bool]:
    more_body = True
    while more_body:
        data = content[:RESPONSE_DATA_BLOCK_SIZE]
        content = content[RESPONSE_DATA_BLOCK_SIZE:]
        more_body = len(content) > 0

        yield data, more_body


def generate_etag(f_size: [float, int], f_modify_time: float) -> str:
    """
    https://tools.ietf.org/html/rfc7232#section-2.3 ETag
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/ETag
    """
    return 'W/"{}"'.format(
        hashlib.md5("{}{}".format(f_size, f_modify_time).encode("utf-8")).hexdigest()
    )


def guess_type(file: Union[str, Path]) -> (Optional[str], Optional[str]):
    """
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Basics_of_HTTP/MIME_types
    https://www.iana.org/assignments/media-types/media-types.xhtml
    """

    if isinstance(file, str):
        file = Path(file)

    elif not isinstance(file, Path):
        raise  # TODO

    content_encoding = None
    config = get_config()

    if config.guess_type_extension.enable:
        # extension guess
        content_type = config.guess_type_extension.filename_mapping.get(file.name)
        if content_type:
            return content_type, content_encoding

        content_type = config.guess_type_extension.suffix_mapping.get(file.suffix)
        if content_type:
            return content_type, content_encoding

    # basic guess
    content_type, content_encoding = orig_guess_type(file, strict=False)
    return content_type, content_encoding


async def detect_charset(
    file: Union[str, Path], content_type: Optional[str]
) -> Optional[str]:
    """
    https://docs.python.org/3/library/codecs.html
    """
    if isinstance(file, str):
        return None

    if content_type is None or not content_type.startswith("text/"):
        return None

    detector = UniversalDetector()
    async with aiofiles.open(file, "rb") as fp:
        for line in await fp.readlines():
            detector.feed(line)
            # print("::::", line, detector.result)
            if detector.done:
                break

    if detector.result.get("confidence") >= 0.6:
        return detector.result.get("encoding")

    return None
