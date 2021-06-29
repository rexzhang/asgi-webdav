from typing import Optional, Union
import re
import gzip
from enum import Enum, auto
from io import BytesIO
from collections.abc import AsyncGenerator
from logging import getLogger

from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_TYPE_RULE,
    DAVCompressLevel,
)
from asgi_webdav.config import get_config
from asgi_webdav.helpers import get_data_generator_from_content
from asgi_webdav.request import DAVRequest

try:
    import brotli
except ImportError:
    brotli = None


logger = getLogger(__name__)


class DAVResponseType(Enum):
    WebDAV = auto()
    WebPage = auto()
    UNDECIDED = auto()


class DAVResponse:
    """provider.implement => provider.DavProvider => DAVDistributor"""

    request: DAVRequest

    status: int
    headers: dict[bytes, bytes]

    def get_data(self):
        return self._data

    def set_data(self, value: Union[bytes, AsyncGenerator]):
        if isinstance(value, bytes):
            self._data = get_data_generator_from_content(value)
            self._data_length = len(value)

        elif isinstance(value, AsyncGenerator):
            self._data = value
            self._data_length = None

        else:
            raise

    data = property(fget=get_data, fset=set_data)
    _data: AsyncGenerator
    _data_length: Optional[int]

    def __init__(
        self,
        status: int,
        headers: Optional[dict[bytes, bytes]] = None,  # extend headers
        response_type: DAVResponseType = DAVResponseType.WebDAV,
        data: Union[bytes, AsyncGenerator] = b"",
        data_length: Optional[int] = None,  # don't assignment when data is bytes
    ):
        self.status = status

        if response_type == DAVResponseType.WebDAV:
            self.headers = {
                b"Content-Type": b"application/xml",
                # b"MS-Author-Via": b"DAV",  # for windows ?
            }
        elif response_type == DAVResponseType.WebPage:
            self.headers = {
                b"Content-Type": b"text/html",
            }
        else:
            self.headers = dict()

        if headers:
            self.headers.update(headers)

        self.data = data
        if data_length is not None:
            self._data_length = data_length

    async def send_in_one_call(self, request: DAVRequest):
        self.request = request

        if request.authorization_info:
            self.headers[b"Authentication-Info"] = request.authorization_info.encode(
                "utf-8"
            )

        logger.debug(self.__repr__())
        if isinstance(self._data_length, int) and self._data_length < 1000:
            # small file
            await self._send_in_direct()
            return

        compression = get_config().compression
        content_type = self.headers.get(b"Content-Type", b"").decode("utf-8")
        if re.match(DEFAULT_COMPRESSION_CONTENT_TYPE_RULE, content_type):
            try_compress = True

        elif (
            compression.user_content_type_rule
            and compression.user_content_type_rule != ""
            and re.match(compression.user_content_type_rule, content_type)
        ):
            try_compress = True

        else:
            try_compress = False

        if try_compress:
            if brotli and compression.enable_brotli and request.accept_encoding.br:
                await BrotliSender(self, compression.level).send()
                return

            if compression.enable_gzip and request.accept_encoding.gzip:
                await GzipSender(self, compression.level).send()
                return

        await self._send_in_direct()

    async def _send_in_direct(self):
        if isinstance(self._data_length, int):
            self.headers.update(
                {
                    b"Content-Length": str(self._data_length).encode("utf-8"),
                }
            )

        # send header
        await self.request.send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": list(self.headers.items()),
            }
        )
        # send data
        async for data, more_body in self._data:
            await self.request.send(
                {
                    "type": "http.response.body",
                    "body": data,
                    "more_body": more_body,
                }
            )

    def __repr__(self):
        fields = [self.status, self._data]
        s = "|".join([str(field) for field in fields])
        try:
            from prettyprinter import pformat

            s += "\n{}".format(pformat(self.headers))
            return s

        except ImportError:
            pass


class CompressionSenderAbc:
    name: bytes

    def __init__(self, response: DAVResponse):
        self.response = response
        self.buffer = BytesIO()

    def write(self, body: bytes):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    async def send(self):
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
        async for body, more_body in self.response.data:
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
                await self.response.request.send(
                    {
                        "type": "http.response.start",
                        "status": self.response.status,
                        "headers": list(self.response.headers.items()),
                    }
                )

            # send body
            await self.response.request.send(
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
