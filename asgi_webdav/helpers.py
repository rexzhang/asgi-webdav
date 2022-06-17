import hashlib
import functools
import os
from typing import Any, TypeVar
import re
import xml.parsers.expat
from collections.abc import AsyncGenerator, Callable
from logging import getLogger
from mimetypes import guess_type as orig_guess_type
from pathlib import Path
import asyncio

import aiofiles
import xmltodict
from chardet import UniversalDetector

from asgi_webdav.config import Config
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE

logger = getLogger(__name__)
T = TypeVar("T")


async def receive_all_data_in_one_call(receive: Callable) -> bytes:
    data = b""
    more_body = True
    while more_body:
        request_data = await receive()
        data += request_data.get("body", b"")
        more_body = request_data.get("more_body")

    return data


async def empty_data_generator() -> AsyncGenerator[bytes, bool]:
    yield b"", False


async def get_data_generator_from_content(
        content: bytes,
        content_range_start: int | None = None,
        content_range_end: int | None = None,
        block_size: int = RESPONSE_DATA_BLOCK_SIZE,
) -> AsyncGenerator[bytes, bool]:
    """
    content_range_start: start with 0
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Range_requests
    """
    if content_range_start is None:
        start = 0
    else:
        start = content_range_start
    if content_range_end is None:
        content_range_end = len(content)

    more_body = True
    while more_body:
        end = start + block_size
        if end > content_range_end:
            end = content_range_end

        data = content[start:end]
        data_length = len(data)
        start += data_length
        more_body = data_length >= block_size

        yield data, more_body


def generate_etag(f_size: [float, int], f_modify_time: float) -> str:
    """
    https://tools.ietf.org/html/rfc7232#section-2.3 ETag
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/ETag
    """
    return 'W/"{}"'.format(
        hashlib.md5("{}{}".format(f_size, f_modify_time).encode("utf-8")).hexdigest()
    )


def guess_type(config: Config, file: str | Path) -> (str | None, str | None):
    """
    https://tools.ietf.org/html/rfc6838
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Basics_of_HTTP/MIME_types
    https://www.iana.org/assignments/media-types/media-types.xhtml
    """

    if isinstance(file, str):
        file = Path(file)

    elif not isinstance(file, Path):
        raise  # TODO

    content_encoding = None

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


async def detect_charset(file: str | Path, content_type: str | None) -> str | None:
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
            if detector.done:
                break

    if detector.result.get("confidence") >= 0.6:
        return detector.result.get("encoding")

    return None


USER_AGENT_PATTERN = r"firefox|chrome|safari"


def is_browser_user_agent(user_agent: bytes | None) -> bool:
    if user_agent is None:
        return False

    user_agent = str(user_agent).lower()
    if re.search(USER_AGENT_PATTERN, user_agent) is None:
        return False

    return True


def dav_dict2xml(data: dict) -> bytes:
    return (
        xmltodict.unparse(data, short_empty_elements=True)
            .replace("\n", "")
            .encode("utf-8")
    )


def dav_xml2dict(data: bytes) -> dict | None:
    try:
        data = xmltodict.parse(data, process_namespaces=True)

    except (xmltodict.ParsingInterrupted, xml.parsers.expat.ExpatError) as e:
        logger.warning(f"parser XML failed, {e}, {data}")
        return None

    return data


async def run_in_threadpool(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


async def iter_fd(file: int, offset: int = None, count: int = None) -> AsyncGenerator[bytes]:
    if offset is not None:
        await run_in_threadpool(os.lseek, file, offset, os.SEEK_SET)
    here = 0
    should_stop = False

    if count is None:
        length = RESPONSE_DATA_BLOCK_SIZE
        while not should_stop:
            data = await run_in_threadpool(os.read, file, length)
            yield data
            if len(data) < length:
                should_stop = True
    else:
        while not should_stop:
            length = min(RESPONSE_DATA_BLOCK_SIZE, count - here)
            should_stop = length == count - here
            here += length
            data = await run_in_threadpool(os.read, file, length)
            # await send({"type": "http.response.body", "body": data,
            #             "more_body": more_body if should_stop else True})
            yield data
