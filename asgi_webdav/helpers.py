from typing import Callable, AsyncGenerator
from datetime import datetime
import hashlib

from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE


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
