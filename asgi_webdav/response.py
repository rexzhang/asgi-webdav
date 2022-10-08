import asyncio
import gzip
import pprint
import re
from collections.abc import AsyncGenerator
from enum import Enum
from io import BytesIO
from logging import getLogger

from asgi_webdav.config import Config, get_config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DEFAULT_COMPRESSION_CONTENT_TYPE_RULE,
    DEFAULT_HIDE_FILE_IN_DIR_RULES,
    DAVCompressLevel,
)
from asgi_webdav.helpers import get_data_generator_from_content
from asgi_webdav.request import DAVRequest

try:
    import brotli
except ImportError:
    brotli = None

logger = getLogger(__name__)


class DAVResponseType(Enum):
    UNDECIDED = 0
    HTML = 1
    XML = 2


class DAVCompressionMethod(Enum):
    NONE = 0
    GZIP = 1
    BROTLI = 2


class DAVResponse:
    """provider.implement => provider.DavProvider => WebDAV"""

    status: int
    headers: dict[bytes, bytes]
    compression_method: DAVCompressionMethod

    def get_content(self):
        return self._content

    def set_content(self, value: bytes | AsyncGenerator):
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

    async def send_in_one_call(self, request: DAVRequest):
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
        if self.can_be_compressed(
            self.headers.get(b"Content-Type", b"").decode("utf-8"),
            config.compression.content_type_user_rule,
        ):
            if (
                brotli is not None
                and config.compression.enable_brotli
                and request.accept_encoding.br
            ):
                self.compression_method = DAVCompressionMethod.BROTLI
                await BrotliSender(self, config.compression.level).send(request)
                return

            if config.compression.enable_gzip and request.accept_encoding.gzip:
                self.compression_method = DAVCompressionMethod.GZIP
                await GzipSender(self, config.compression.level).send(request)
                return

        self.compression_method = DAVCompressionMethod.NONE
        await self._send_in_direct(request)

    async def _send_in_direct(self, request: DAVRequest):
        if isinstance(self.content_length, int):
            self.headers.update(
                {
                    b"Content-Length": str(self.content_length).encode("utf-8"),
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

    def __repr__(self):
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


class CompressionSenderAbc:
    name: bytes

    def __init__(self, response: DAVResponse):
        self.response = response
        self.buffer = BytesIO()

    def write(self, body: bytes):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    async def send(self, request: DAVRequest):
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
            self.write(body)
            if not more_body:
                self.close()
            body = self.buffer.getvalue()

            self.buffer.seek(0)
            self.buffer.truncate()

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
                    "body": body,
                    "more_body": more_body,
                }
            )


class GzipSender(CompressionSenderAbc):
    """
    https://en.wikipedia.org/wiki/Gzip
    https://developer.mozilla.org/en-US/docs/Glossary/GZip_compression
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
        self.compressor = gzip.GzipFile(
            mode="wb", compresslevel=level, fileobj=self.buffer
        )

    def write(self, body: bytes):
        self.compressor.write(body)

    def close(self):
        self.compressor.close()


class BrotliSender(CompressionSenderAbc):
    """
    https://datatracker.ietf.org/doc/html/rfc7932
    https://github.com/google/brotli
    https://caniuse.com/brotli
    https://developer.mozilla.org/en-US/docs/Glossary/brotli_compression
    """

    def __init__(self, response: DAVResponse, compress_level: DAVCompressLevel):
        super().__init__(response)

        if compress_level == DAVCompressLevel.FAST:
            level = 1
        elif compress_level == DAVCompressLevel.BEST:
            level = 11
        else:
            level = 4

        self.name = b"br"
        self.compressor = brotli.Compressor(mode=brotli.MODE_TEXT, quality=level)

    def write(self, body: bytes):
        # https://github.com/google/brotli/blob/master/python/brotli.py
        self.buffer.write(self.compressor.process(body))

    def close(self):
        self.buffer.write(self.compressor.finish())


class DAVHideFileInDir:
    _data_rules: dict[str, str]
    _data_rules_default: str | None

    def __init__(self, config: Config):
        self.enable = config.hide_file_in_dir.enable
        if not self.enable:
            return

        self._ua_to_rule_mapping = dict()
        self._ua_to_rule_mapping_lock = asyncio.Lock()

        self._data_rules = dict()
        self._data_rules_default = None
        self._data_skipped_ua_set = set()  # for missed ua regex: ""

        if config.hide_file_in_dir.enable_default_rules:
            self._data_rules.update(DEFAULT_HIDE_FILE_IN_DIR_RULES)

        for k, v in config.hide_file_in_dir.user_rules.items():
            if k in self._data_rules:
                self._data_rules[k] = f"{self._data_rules[k]}|{v}"
            else:
                self._data_rules[k] = v

        if "" in self._data_rules:
            self._data_rules_default = self._data_rules.pop("")

    @staticmethod
    def _merge_rules(rules_a: str | None, rules_b: str) -> str:
        if rules_a is None:
            return rules_b

        return f"{rules_a}|{rules_b}"

    def get_rule_by_client_user_agent(self, ua: str) -> str | None:
        ua_matched = False
        result = None

        for ua_regex in self._data_rules.keys():
            # if len(ua_regex) == 0 or re.match(ua_regex, ua) is not None:
            if re.match(ua_regex, ua) is not None:
                ua_matched = True

                result = self._merge_rules(result, self._data_rules.get(ua_regex))

        if self._data_rules_default is not None:
            result = self._merge_rules(result, self._data_rules_default)

        if not ua_matched:
            self._data_skipped_ua_set.add(ua)

        return result

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

        # match rule with ua
        if ua in self._data_skipped_ua_set:
            if self._data_rules_default is None:
                return False

            rule = self._data_rules_default

        else:
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
