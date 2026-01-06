from __future__ import annotations

import asyncio
import gzip
import pprint
import re
import sys
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from logging import getLogger

from asgiref.typing import ASGISendCallable

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd  # type: ignore # pragma: no cover

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DEFAULT_COMPRESSION_CONTENT_TYPE_RULE,
    DEFAULT_HIDE_FILE_IN_DIR_RULES,
    RESPONSE_DATA_BLOCK_SIZE,
    DAVCompressLevel,
    DAVMethod,
    DAVResponseBodyGenerator,
    DAVResponseContentRange,
    DAVResponseContentType,
    DAVSenderName,
)
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)


async def get_response_body_generator(
    content: bytes | None = None,
    content_range_start: int | None = None,
    content_range_end: int | None = None,
    block_size: int = RESPONSE_DATA_BLOCK_SIZE,
) -> DAVResponseBodyGenerator:
    if content is None:
        # return empty response
        yield b"", False
        return

    # have content
    if content_range_start is None:
        start = 0
    else:
        start = content_range_start
    if content_range_end is None:
        content_range_end = len(content) - 1

    more_body = True
    while more_body:
        end = start + block_size - 1
        if end >= content_range_end:
            end = content_range_end
            body = content[start : end + 1]

            more_body = False

        else:
            body = content[start : end + 1]

            more_body = True
            start += block_size

        yield body, more_body


@dataclass(slots=True)
class DAVResponse:
    """provider.implement => provider.DavProvider => WebDAV
    - when content is DAVResponseBodyGenerator, better use content_length
    """

    status: int
    headers: dict[bytes, bytes] = field(default_factory=dict)

    content: bytes | DAVResponseBodyGenerator = b""
    content_body_generator: DAVResponseBodyGenerator = field(init=False)
    content_length: int | None = None  # for content_range is None
    content_range: DAVResponseContentRange | None = None
    content_range_support: bool = False

    response_type: DAVResponseContentType = DAVResponseContentType.HTML
    matched_sender_name: DAVSenderName = field(init=False)

    def __post_init__(self) -> None:
        # content_body_generator
        if isinstance(self.content, bytes):
            self.content_body_generator = get_response_body_generator(self.content)

            if self.content_length is None:
                self.content_length = len(self.content)
        else:
            self.content_body_generator = self.content

        if self.content_range_support:
            # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Accept-Ranges
            # - DAVSender 可能不支持分段, 但资源支持分段
            self.headers[b"Accept-Ranges"] = b"bytes"

        # response_type
        match self.response_type:
            case DAVResponseContentType.HTML:
                self.headers[b"Content-Type"] = b"text/html"
            case DAVResponseContentType.XML:
                self.headers[b"Content-Type"] = b"application/xml"
                # b"MS-Author-Via": b"DAV",  # for windows ?

    def process(self, config: Config, request: DAVRequest) -> None:
        if request.authorization_info:
            self.headers[b"Authentication-Info"] = request.authorization_info

        self.matched_sender_name = self._match_dav_sender(
            config=config,
            request_accept_encoding=request.accept_encoding,
            response_content_type_from_header=self.headers.get(
                b"Content-Type", b""
            ).decode(),
        )

    @staticmethod
    def _can_be_compressed(
        content_type_from_header: str, content_type_user_rule: str
    ) -> bool:
        if re.match(DEFAULT_COMPRESSION_CONTENT_TYPE_RULE, content_type_from_header):
            return True

        elif content_type_user_rule != "" and re.match(
            content_type_user_rule, content_type_from_header
        ):
            return True

        return False

    def _match_dav_sender(
        self,
        config: Config,
        request_accept_encoding: str,
        response_content_type_from_header: str,
    ) -> DAVSenderName:
        #
        if not config.compression.enable or self.content_range:
            return DAVSenderName.RAW

        if (
            isinstance(self.content_length, int)
            and self.content_length < DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH
        ):
            # small file
            return DAVSenderName.RAW

        if not self._can_be_compressed(
            response_content_type_from_header,
            config.compression.content_type_user_rule,
        ):
            return DAVSenderName.RAW

        # check accept_encoding from request
        request_accept_encoding_set = {
            item.strip(" ") for item in request_accept_encoding.split(",")
        }

        if (
            config.compression.enable_zstd
            and DAVSenderName.ZSTD.value in request_accept_encoding_set  # type: ignore # py3.11+ EnumStr
        ):
            return DAVSenderName.ZSTD

        if (
            config.compression.enable_deflate
            and DAVSenderName.DEFLATE.value in request_accept_encoding_set  # type: ignore # py3.11+ EnumStr
        ):
            return DAVSenderName.DEFLATE

        if (
            config.compression.enable_gzip
            and DAVSenderName.GZIP.value in request_accept_encoding_set  # type: ignore # py3.11+ EnumStr
        ):
            return DAVSenderName.GZIP

        return DAVSenderName.RAW

    def __repr__(self) -> str:
        fields = [
            self.status,
            (
                "bytes"
                if isinstance(self.content_body_generator, bytes)
                else "DAVResponseBodyGenerator"
            ),
            self.content_length,
            self.content_range,
            self.response_type,
            (
                self.matched_sender_name
                if hasattr(self, "compression_method")
                else "UNSET"
            ),
        ]
        s = "|".join([str(field) for field in fields])

        s += f"\n{pprint.pformat(self.headers)}"
        return s


class DAVResponseMethodNotAllowed(DAVResponse):
    def __init__(self, method: DAVMethod):
        content = f"method:{method.value} is not support method".encode()
        super().__init__(status=405, content=content, content_length=len(content))


class DAVSenderAbc:
    name: bytes = b"DAVSenderAbc"
    response: DAVResponse

    def __init__(self, config: Config, response: DAVResponse):
        self.response = response

    async def send_it(self, send: ASGISendCallable) -> None:
        raise NotImplementedError  # pragma: no cover


class DAVSenderRaw(DAVSenderAbc):
    name: bytes = b"DAVSenderRaw"

    def __init__(self, config: Config, response: DAVResponse):
        super().__init__(config=config, response=response)

        if response.content_range:
            # Content-Range only work on RAW mode
            # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Content-Range
            # Content-Range: <unit> <range-start>-<range-end>/<size>
            response.headers.update(
                {
                    b"Content-Range": "bytes {}-{}/{}".format(
                        response.content_range.content_start,
                        response.content_range.content_end,
                        response.content_range.file_size,
                    ).encode(),
                    b"Content-Length": str(
                        response.content_range.content_length
                    ).encode(),
                }
            )

        else:
            if isinstance(response.content_length, int):
                response.headers[b"Content-Length"] = str(
                    response.content_length
                ).encode()

    async def send_it(self, send: ASGISendCallable) -> None:
        # send header
        await send(
            {
                "type": "http.response.start",
                "status": self.response.status,
                "headers": list(self.response.headers.items()),
                "trailers": True,
            }
        )
        # send body
        async for body, more_body in self.response.content_body_generator:
            await send(
                {
                    "type": "http.response.body",
                    "body": body,
                    "more_body": more_body,
                }
            )


class DAVSenderCompressionAbc(DAVSenderAbc):
    name: bytes = b"SenderCompressionAbc"

    compress_level: int

    def __init__(self, config: Config, response: DAVResponse):
        super().__init__(config=config, response=response)

        """
        Content-Length rule:
        https://www.oreilly.com/library/view/http-the-definitive/1565925092/ch15s02.html
        """
        response.headers.update(
            {
                b"Content-Encoding": self.name,
                b"Transfer-Encoding": b"chunked",
            }
        )
        response.headers.pop(b"Content-Length", None)
        if response.content_length:
            response.headers.update(
                {
                    b"X-Uncompressed-Content-Length": str(
                        response.content_length
                    ).encode()
                }
            )

    def _compress(self, body: bytes) -> bytes:
        raise NotImplementedError  # pragma: no cover

    def _flush(self) -> bytes:
        raise NotImplementedError  # pragma: no cover

    async def send_it(self, send: ASGISendCallable) -> None:
        # send headers
        await send(
            {
                "type": "http.response.start",
                "status": self.response.status,
                "headers": list(self.response.headers.items()),
                "trailers": True,
            }
        )

        # send body
        async for body, more_body in self.response.content_body_generator:
            data = self._compress(body)
            if not more_body:
                data += self._flush()

            if not data:
                continue  # pragma: no cover

            await send(
                {
                    "type": "http.response.body",
                    "body": data,
                    "more_body": more_body,
                }
            )


class DAVSenderZstd(DAVSenderCompressionAbc):
    """
    https://en.wikipedia.org/wiki/Zstd
    https://facebook.github.io/zstd/
    https://developer.mozilla.org/en-US/docs/Glossary/Zstandard_compression
    https://docs.python.org/zh-cn/3.14/library/compression.zstd.html
    """

    name: bytes = b"zstd"
    compressor: zstd.ZstdCompressor

    def __init__(self, config: Config, response: DAVResponse):
        super().__init__(config=config, response=response)

        if config.compression.level == DAVCompressLevel.FAST:
            level = 1
        elif config.compression.level == DAVCompressLevel.BEST:
            level = 19
        else:
            level = zstd.COMPRESSION_LEVEL_DEFAULT

        self.compress_level = level
        self.compressor = zstd.ZstdCompressor(level=level)

    def _compress(self, body: bytes) -> bytes:
        return self.compressor.compress(body)  # type: ignore

    def _flush(self) -> bytes:
        return self.compressor.flush()  # type: ignore


class DAVSenderDeflate(DAVSenderCompressionAbc):
    """
    https://en.wikipedia.org/wiki/Gzip
    https://developer.mozilla.org/en-US/docs/Glossary/GZip_compression
    https://docs.python.org/3.14/library/gzip.html
    """

    name: bytes = b"deflate"

    def __init__(self, config: Config, response: DAVResponse):
        super().__init__(config=config, response=response)

        if config.compression.level == DAVCompressLevel.FAST:
            level = zlib.Z_BEST_SPEED
        elif config.compression.level == DAVCompressLevel.BEST:
            level = zlib.Z_BEST_COMPRESSION
        else:
            level = zlib.Z_DEFAULT_COMPRESSION

        self.compress_level = level
        self.compressor = zlib.compressobj(level)

    def _compress(self, body: bytes) -> bytes:
        return self.compressor.compress(body)

    def _flush(self) -> bytes:
        return self.compressor.flush()


class DAVSenderGzip(DAVSenderCompressionAbc):
    """
    https://en.wikipedia.org/wiki/Gzip
    https://developer.mozilla.org/en-US/docs/Glossary/GZip_compression
    https://docs.python.org/3.14/library/gzip.html
    """

    name: bytes = b"gzip"
    buffer: BytesIO

    def __init__(self, config: Config, response: DAVResponse):
        super().__init__(config=config, response=response)

        if config.compression.level == DAVCompressLevel.FAST:
            level = 1
        elif config.compression.level == DAVCompressLevel.BEST:
            level = 9
        else:
            level = 4

        self.buffer = BytesIO()

        self.compress_level = level
        self.compressor = gzip.GzipFile(
            mode="wb", compresslevel=level, fileobj=self.buffer
        )

    def _compress(self, body: bytes) -> bytes:
        self.compressor.write(body)
        return b""

    def _flush(self) -> bytes:
        self.compressor.flush()
        self.compressor.close()
        data = self.buffer.getvalue()

        self.buffer.seek(0)
        self.buffer.truncate()

        return data


def get_dav_sender(config: Config, response: DAVResponse) -> DAVSenderAbc:
    match response.matched_sender_name:
        case DAVSenderName.ZSTD:
            return DAVSenderZstd(config=config, response=response)

        case DAVSenderName.DEFLATE:
            return DAVSenderDeflate(config=config, response=response)

        case DAVSenderName.GZIP:
            return DAVSenderGzip(config=config, response=response)

    return DAVSenderRaw(config=config, response=response)


class DAVHideFileInDir:
    _ua_to_rule_mapping: dict[str, str]
    _ua_to_rule_mapping_lock: asyncio.Lock

    _data_rules: dict[str, str]
    _data_rules_basic: str | None

    def __init__(self, config: Config):
        self.enable = config.hide_file_in_dir.enable
        if not self.enable:
            return

        self._ua_to_rule_mapping = dict()
        self._ua_to_rule_mapping_lock = asyncio.Lock()

        self._data_rules = dict()
        self._data_rules_basic = None

        # merge default rules
        if config.hide_file_in_dir.enable_default_rules:
            self._data_rules.update(DEFAULT_HIDE_FILE_IN_DIR_RULES)

        # merge user's rules
        for k, v in config.hide_file_in_dir.user_rules.items():
            if k in self._data_rules:
                self._data_rules[k] = self._merge_rules(self._data_rules[k], v)
            else:
                self._data_rules[k] = v

        if "" in self._data_rules:
            self._data_rules_basic = self._data_rules.pop("")

            # merge basic rule to others
            for k, v in self._data_rules.items():
                self._data_rules[k] = self._merge_rules(self._data_rules_basic, v)

    @staticmethod
    def _merge_rules(rules_a: str | None, rules_b: str) -> str:
        if rules_a is None:
            return rules_b

        return f"{rules_a}|{rules_b}"

    def get_rule_by_client_user_agent(self, ua: str) -> str | None:
        for ua_regex in self._data_rules.keys():
            if re.match(ua_regex, ua) is not None:
                return self._data_rules.get(ua_regex)

        return self._data_rules_basic

    @staticmethod
    def is_match_file_name(rule: str, file_name: str) -> bool:
        if re.match(rule, file_name):
            logger.debug(f"Rule:{rule}, File:{file_name}, hide it")
            return True

        logger.debug(f"Rule:{rule}, File:{file_name}, show it")
        return False

    async def is_match_hide_file_in_dir(self, ua: str, file_name: str) -> bool:
        if not self.enable:
            return False

        async with self._ua_to_rule_mapping_lock:
            rule = self._ua_to_rule_mapping.get(ua)
            if rule:
                return self.is_match_file_name(rule, file_name)

            rule = self.get_rule_by_client_user_agent(ua)
            if rule:
                self._ua_to_rule_mapping.update({ua: rule})
                return self.is_match_file_name(rule, file_name)

        return False
