from __future__ import annotations

import hashlib
import re
import sys
import xml.parsers.expat
from logging import getLogger
from os import getenv
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

logger = getLogger(__name__)


async def receive_all_data_in_one_call(receive: ASGIReceiveCallable) -> bytes:
    data = b""
    more_body = True
    while more_body:
        request_data: HTTPRequestEvent = await receive()  # type: ignore
        data += request_data.get("body")
        more_body = request_data.get("more_body")

    return data


def generate_etag(f_size: int, f_modify_time: float) -> str:
    """
    https://tools.ietf.org/html/rfc7232#section-2.3 ETag
    https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/ETag
    """
    return 'W/"{}"'.format(hashlib.md5(f"{f_size}{f_modify_time}".encode()).hexdigest())


def is_etag(etag: str) -> bool:
    return re.match(r'W/"[a-f0-9]{32}"', etag) is not None


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


def is_browser_user_agent(user_agent: str | bytes | None) -> bool:
    match user_agent:
        case None:
            return False
        case str():
            if re.search(USER_AGENT_PATTERN, user_agent.lower()) is None:
                return False
        case bytes():
            if re.search(USER_AGENT_PATTERN, user_agent.decode().lower()) is None:
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


def get_timezone() -> ZoneInfo:
    # TODO: support get zone info from config, maybe?
    env_value = getenv("TZ")
    if env_value is None:
        env_value = "UTC"
        logger.info("get timezone from env failed, set default timezone: UTC")

    try:
        timezone = ZoneInfo(env_value)

    except ZoneInfoNotFoundError:
        logger.error(f"get invalid timezone from env: {env_value}")
        timezone = ZoneInfo("UTC")

    return timezone


def get_str_from_first_brackets(input: str, start: str, end: str) -> str | None:
    begin_index = input.find(start)
    end_index = input.find(end)

    if begin_index == -1 or end_index == -1:
        return None

    return input[begin_index + 1 : end_index]
