import asyncio
import gzip
import pprint
import re
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from logging import getLogger

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd  # type: ignore

from asgi_webdav.config import Config, get_global_config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DEFAULT_COMPRESSION_CONTENT_TYPE_RULE,
    DEFAULT_HIDE_FILE_IN_DIR_RULES,
    RESPONSE_DATA_BLOCK_SIZE,
    DAVCompressLevel,
    DAVMethod,
    DAVResponseBodyGenerator,
    DAVUpperEnumAbc,
)
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)


class DAVResponseType(Enum):
    UNDECIDED = 0
    HTML = 1
    XML = 2


class DAVCompressionMethod(DAVUpperEnumAbc):
    NONE = auto()
    GZIP = auto()
    ZSTD = auto()


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

    # return response with data
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


@dataclass(slots=True)
class DAVResponse:
    """provider.implement => provider.DavProvider => WebDAV"""

    status: int
    headers: dict[bytes, bytes] = field(default_factory=dict)

    content: bytes | DAVResponseBodyGenerator = b""
    content_body_generator: DAVResponseBodyGenerator = field(init=False)
    content_length: int | None = None
    content_range: bool = False
    content_range_start: int | None = None
    content_range_end: int | None = None  # TODO implement

    response_type: DAVResponseType = DAVResponseType.HTML
    compression_method: DAVCompressionMethod = field(init=False)

    config: Config = field(init=False)

    def __post_init__(self) -> None:
        if self.response_type == DAVResponseType.HTML:
            self.headers.update(
                {
                    b"Content-Type": b"text/html",
                }
            )
        elif self.response_type == DAVResponseType.XML:
            self.headers.update(
                {
                    b"Content-Type": b"application/xml",
                    # b"MS-Author-Via": b"DAV",  # for windows ?
                }
            )

        if isinstance(self.content, bytes):
            self.content_body_generator = get_response_body_generator(self.content)

            if self.content_length is None:
                self.content_length = len(self.content)
        else:
            self.content_body_generator = self.content

        # if content_range_start is not None or content_range_end is not None:
        if self.content_length is not None and self.content_range_start is not None:
            self.content_range = True
            self.content_length = self.content_length - self.content_range_start

            # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Content-Range
            # Content-Range: <unit> <range-start>-<range-end>/<size>
            self.headers.update(
                {
                    b"Content-Range": "bytes {}-{}/{}".format(
                        self.content_range_start,
                        self.content_length,
                        self.content_length,
                    ).encode("utf-8"),
                }
            )

        # config
        self.config = get_global_config()

    async def send_in_one_call(self, request: DAVRequest) -> None:
        if request.authorization_info:
            self.headers[b"Authentication-Info"] = request.authorization_info

        logger.debug(self.__repr__())
        if (
            isinstance(self.content_length, int)
            and self.content_length < DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH
        ):
            # small file
            await self._send_in_one_body(request)
            return

        self.compression_method = self._match_compression_method(
            request.accept_encoding,
            self.headers.get(b"Content-Type", b"").decode("utf-8"),
        )
        match self.compression_method:
            case DAVCompressionMethod.ZSTD:
                await CompressionSenderZstd(self, self.config.compression.level).send(
                    request
                )

            case DAVCompressionMethod.GZIP:
                await CompressionSenderGzip(self, self.config.compression.level).send(
                    request
                )

            case _:
                await self._send_in_one_body(request)

        return

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

    def _match_compression_method(
        self, request_accept_encoding: str, response_content_type_from_header: str
    ) -> DAVCompressionMethod:
        if not self.config.compression.enable and self._can_be_compressed(
            response_content_type_from_header,
            self.config.compression.content_type_user_rule,
        ):
            return DAVCompressionMethod.NONE

        if (
            self.config.compression.enable_zstd
            and DAVCompressionMethod.ZSTD.value in request_accept_encoding  # type: ignore # py3.11+ EnumStr
        ):
            return DAVCompressionMethod.ZSTD

        if (
            self.config.compression.enable_gzip
            and DAVCompressionMethod.GZIP.value in request_accept_encoding  # type: ignore # py3.11+ EnumStr
        ):
            return DAVCompressionMethod.GZIP

        return DAVCompressionMethod.NONE

    async def _send_in_one_body(self, request: DAVRequest) -> None:
        response_content_length = self.content_length

        # Update header
        if request.content_range_end:
            response_content_length = (
                request.content_range_end - request.content_range_start + 1
            )
            self.headers.update(
                {
                    b"Content-Range": "bytes {}-{}/{}".format(
                        request.content_range_start,
                        request.content_range_end,
                        self.content_length,
                    ).encode("utf-8"),
                }
            )

        if isinstance(response_content_length, int):
            self.headers.update(
                {
                    b"Content-Length": str(response_content_length).encode("utf-8"),
                }
            )

        # send header
        await request.send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": list(self.headers.items()),
                "trailers": True,
            }
        )
        # send data
        async for data, more_body in self.content_body_generator:
            await request.send(
                {
                    "type": "http.response.body",
                    "body": data,
                    "more_body": more_body,
                }
            )

    def __repr__(self) -> str:
        fields = [
            self.status,
            self.content_length,
            (
                "bytes"
                if isinstance(self.content_body_generator, bytes)
                else "DAVResponseBodyGenerator"
            ),
            self.content_range,
            self.content_range_start,
        ]
        s = "|".join([str(field) for field in fields])

        s += f"\n{pprint.pformat(self.headers)}"
        return s


class DAVResponseMethodNotAllowed(DAVResponse):

    def __init__(self, method: DAVMethod):
        content = f"method:{method} is not support method".encode()
        super().__init__(status=405, content=content, content_length=len(content))


class CompressionSenderAbc:
    name: bytes

    def __init__(self, response: DAVResponse):
        self.response = response
        # self.buffer = BytesIO()

    def compress(self, body: bytes) -> bytes:
        raise NotImplementedError

    def flush(self) -> bytes:
        raise NotImplementedError

    async def send(self, request: DAVRequest) -> None:
        """
        Content-Length rule:
        https://www.oreilly.com/library/view/http-the-definitive/1565925092/ch15s02.html
        """
        self.response.headers.update(
            {
                b"Content-Encoding": self.name,
                b"Transfer-Encoding": b"chunked",  # 声明开启分块
            }
        )
        if self.response.content_length:
            self.response.headers.update(
                {
                    b"X-Uncompressed-Content-Length": str(
                        self.response.content_length
                    ).encode()
                }
            )

        first = True
        async for body, more_body in self.response.content_body_generator:
            # get and compress body

            data = self.compress(body)
            if not more_body:
                data += self.flush()

            if first:
                first = False

                # send headers
                await request.send(
                    {
                        "type": "http.response.start",
                        "status": self.response.status,
                        "headers": list(self.response.headers.items()),
                        "trailers": True,
                    }
                )

            # send body
            await request.send(
                {
                    "type": "http.response.body",
                    "body": data,
                    "more_body": more_body,
                }
            )


class CompressionSenderGzip(CompressionSenderAbc):
    """
    https://en.wikipedia.org/wiki/Gzip
    https://developer.mozilla.org/en-US/docs/Glossary/GZip_compression
    https://docs.python.org/3.14/library/gzip.html
    """

    def __init__(self, response: DAVResponse, compress_level: DAVCompressLevel):
        super().__init__(response)

        if compress_level == DAVCompressLevel.FAST:
            level = 1
        elif compress_level == DAVCompressLevel.BEST:
            level = 9
        else:
            level = 4

        self.name = b"gzip"
        self._level = level

    def compress(self, body: bytes) -> bytes:
        return gzip.compress(body, compresslevel=self._level)

    def flush(self) -> bytes:
        return b""


class CompressionSenderZstd(CompressionSenderAbc):
    """
    https://en.wikipedia.org/wiki/Zstd
    https://facebook.github.io/zstd/
    https://developer.mozilla.org/en-US/docs/Glossary/Zstandard_compression
    https://docs.python.org/zh-cn/3.14/library/compression.zstd.html
    """

    def __init__(self, response: DAVResponse, compress_level: DAVCompressLevel):
        super().__init__(response)

        if compress_level == DAVCompressLevel.FAST:
            level = 1
        elif compress_level == DAVCompressLevel.BEST:
            level = 19
        else:
            level = 3  # compression.zstd.COMPRESSION_LEVEL_DEFAULT

        self.name = b"zstd"
        self._compressor = zstd.ZstdCompressor(level=level)

    def compress(self, body: bytes) -> bytes:
        return self._compressor.compress(body)

    def flush(self) -> bytes:
        return self._compressor.flush()


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
