import hashlib
import re
import sys
import xml.parsers.expat
from collections.abc import AsyncGenerator
from logging import getLogger
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# https://docs.python.org/zh-cn/3/library/mimetypes.html#mimetypes.guess_type
# Deprecated since version 3.13: Passing a file path instead of URL is soft deprecated. Use guess_file_type() for this.
if sys.version_info >= (3, 13):
    from mimetypes import (
        guess_file_type as mimetypes_guess_file_type,  # pragma: no cover
    )

else:
    from mimetypes import guess_type as mimetypes_guess_file_type  # pragma: no cover

import aiofiles
import xmltodict
from asgiref.typing import ASGIReceiveCallable, HTTPRequestEvent
from chardet import UniversalDetector

from asgi_webdav.config import Config
from asgi_webdav.constants import RESPONSE_DATA_BLOCK_SIZE
from asgi_webdav.exception import DAVException

logger = getLogger(__name__)


async def receive_all_data_in_one_call(receive: ASGIReceiveCallable) -> bytes:
    data = b""
    more_body = True
    while more_body:
        request_data: HTTPRequestEvent = await receive()  # type: ignore
        data += request_data.get("body")
        more_body = request_data.get("more_body")

    return data


async def empty_data_generator() -> AsyncGenerator[tuple[bytes, bool], None]:
    yield b"", False


async def get_data_generator_from_content(
    content: bytes,
    content_range_start: int | None = None,
    content_range_end: int | None = None,
    block_size: int = RESPONSE_DATA_BLOCK_SIZE,
) -> AsyncGenerator[tuple[bytes, bool], None]:
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


def generate_etag(f_size: int, f_modify_time: float) -> str:
    """
    https://tools.ietf.org/html/rfc7232#section-2.3 ETag
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/ETag
    """
    return 'W/"{}"'.format(hashlib.md5(f"{f_size}{f_modify_time}".encode()).hexdigest())


def guess_type(config: Config, file: str | Path) -> tuple[str | None, str | None]:
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
    content_type, content_encoding = mimetypes_guess_file_type(file, strict=False)
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

    if re.search(USER_AGENT_PATTERN, user_agent.decode("utf-8").lower()) is None:
        return False

    return True


def get_xml_from_dict(data: dict[str, Any]) -> bytes:
    return (
        xmltodict.unparse(data, short_empty_elements=True)
        .replace("\n", "")
        .encode("utf-8")
    )


def get_dict_from_xml(data: bytes, propert_type: str) -> dict[str, Any]:
    try:
        result = xmltodict.parse(data, process_namespaces=True)

    except (xmltodict.ParsingInterrupted, xml.parsers.expat.ExpatError) as e:
        logger.warning(f"parser XML {propert_type} failed: {e}, xml: {data.decode()}")
        return {}

    try:
        result = result[f"DAV::{propert_type}"]

    except (ValueError, KeyError) as e:
        logger.warning(f"parser XML {propert_type} failed: {e}, xml: {data.decode()}")
        return {}

    return result  # type: ignore


def paser_timezone_key(tz_key: str) -> str:
    try:
        zone_info = ZoneInfo(tz_key)

    except ZoneInfoNotFoundError:
        # TODO: rewrite, move into config
        raise DAVException(f"Invalid timezone: {tz_key}")

    return zone_info.key
