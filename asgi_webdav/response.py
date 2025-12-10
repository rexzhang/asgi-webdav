import asyncio
import gzip
import pprint
import re
import sys
from collections.abc import AsyncGenerator
from enum import Enum
from logging import getLogger

if sys.version_info >= (3, 14):
    import zstd
else:
    from backports import zstd

from asgi_webdav.config import Config, get_config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DEFAULT_COMPRESSION_CONTENT_TYPE_RULE,
    DEFAULT_HIDE_FILE_IN_DIR_RULES,
    DAVCompressLevel,
    DAVMethod,
)
from asgi_webdav.helpers import get_data_generator_from_content
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)


class DAVResponseType(Enum):
    UNDECIDED = 0
    HTML = 1
    XML = 2


class DAVCompressionMethod(Enum):
    """
    Python 3.11 才支持 StrEnum
        然后使用 auto() 生成期望的枚举值
        并可以不使用 .value 做匹配
    """

    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"


class DAVResponse:
    """provider.implement => provider.DavProvider => WebDAV"""

    status: int
    headers: dict[bytes, bytes]
    compression_method: DAVCompressionMethod

    def get_content(self) -> AsyncGenerator:
        return self._content

    def set_content(self, value: bytes | AsyncGenerator) -> None:
        if isinstance(value, bytes):
            self._content = get_data_generator_from_content(value)
            self.content_length = len(value)

        elif isinstance(value, AsyncGenerator):
            self._content = value
            self.content_length = None

        else:
            raise

    content = property(fget=get_content, fset=set_content)
    _content: AsyncGenerator
    content_length: int | None
    content_range: bool = False
    content_range_start: int | None = None

    def __init__(
        self,
        status: int,
        headers: dict[bytes, bytes] | None = None,  # extend headers
        response_type: DAVResponseType = DAVResponseType.HTML,
        content: bytes | AsyncGenerator = b"",
        content_length: int | None = None,  # don't assignment when data is bytes
        content_range_start: int | None = None,
    ):
        self.status = status

        if response_type == DAVResponseType.HTML:
            self.headers = {
                b"Content-Type": b"text/html",
            }
        elif response_type == DAVResponseType.XML:
            self.headers = {
                b"Content-Type": b"application/xml",
                # b"MS-Author-Via": b"DAV",  # for windows ?
            }
        else:
            self.headers = dict()

        if headers:
            self.headers.update(headers)

        self.content = content
        if content_length is not None:
            self.content_length = content_length

        # if content_range_start is not None or content_range_end is not None:
        if content_length is not None and content_range_start is not None:
            self.content_range = True
            self.content_range_start = content_range_start
            self.content_length = content_length - content_range_start

            # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Content-Range
            # Content-Range: <unit> <range-start>-<range-end>/<size>
            self.headers.update(
                {
                    b"Content-Range": "bytes {}-{}/{}".format(
                        content_range_start, content_length, content_length
                    ).encode("utf-8"),
                }
            )

    @staticmethod
    def can_be_compressed(
        content_type_from_header: str, content_type_user_rule: str
    ) -> bool:
        if re.match(DEFAULT_COMPRESSION_CONTENT_TYPE_RULE, content_type_from_header):
            return True

        elif content_type_user_rule != "" and re.match(
            content_type_user_rule, content_type_from_header
        ):
            return True

        return False

    async def send_in_one_call(self, request: DAVRequest) -> None:
        if request.authorization_info:
            self.headers[b"Authentication-Info"] = request.authorization_info

        logger.debug(self.__repr__())
        if (
            isinstance(self.content_length, int)
            and self.content_length < DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH
        ):
            # small file
            await self._send_in_direct(request)
            return

        config = get_config()
        if config.compression.enable and self.can_be_compressed(
            self.headers.get(b"Content-Type", b"").decode("utf-8"),
            config.compression.content_type_user_rule,
        ):
            if (
                config.compression.enable_zstd
                and DAVCompressionMethod.ZSTD.value in request.accept_encoding
            ):
                self.compression_method = DAVCompressionMethod.ZSTD
                await CompressionSenderZstd(self, config.compression.level).send(
                    request
                )
                return

            if (
                config.compression.enable_gzip
                and DAVCompressionMethod.GZIP.value in request.accept_encoding
            ):
                self.compression_method = DAVCompressionMethod.GZIP
                await CompressionSenderGzip(self, config.compression.level).send(
                    request
                )
                return

        self.compression_method = DAVCompressionMethod.NONE
        await self._send_in_direct(request)

    async def _send_in_direct(self, request: DAVRequest) -> None:
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
            }
        )
        # send data
        async for data, more_body in self._content:
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
            "bytes" if isinstance(self._content, bytes) else "AsyncGenerator",
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
            }
        )

        first = True
        async for body, more_body in self.response.content:
            # get and compress body

            data = self.compress(body)
            if not more_body:
                data += self.flush()

            if first:
                first = False

                # update headers
                if more_body:
                    try:
                        self.response.headers.pop(b"Content-Length")
                    except KeyError:
                        pass

                else:
                    self.response.headers.update(
                        {
                            b"Content-Length": str(len(body)).encode("utf-8"),
                        }
                    )

                # send headers
                await request.send(
                    {
                        "type": "http.response.start",
                        "status": self.response.status,
                        "headers": list(self.response.headers.items()),
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
            if ua in self._ua_to_rule_mapping:
                rule = self._ua_to_rule_mapping.get(ua)

            else:
                rule = self.get_rule_by_client_user_agent(ua)
                if rule is None:
                    return False

                self._ua_to_rule_mapping.update({ua: rule})

        # match file name with rule
        return self.is_match_file_name(rule, file_name)
