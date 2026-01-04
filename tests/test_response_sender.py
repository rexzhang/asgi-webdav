import gzip
import sys
import zlib

from icecream import ic

if sys.version_info >= (3, 14):
    from compression import zstd
else:
    from backports import zstd  # type: ignore # pragma: no cover

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DAVCompressLevel,
    DAVRangeType,
    DAVResponseContentRange,
)
from asgi_webdav.response import (
    DAVResponse,
    DAVSenderAbc,
    DAVSenderCompressionAbc,
    DAVSenderDeflate,
    DAVSenderGzip,
    DAVSenderRaw,
    DAVSenderZstd,
)

from .kits.asgi import ASGIFakeSend
from .kits.common import get_bytes, get_generate_random_bytes

DECOMPRESS_CONTENT_1 = get_bytes(DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH)
DECOMPRESS_CONTENT_2 = get_generate_random_bytes(
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH
)


class BaseTestSender:
    sender_name: bytes

    def get_dav_sender(self, config: Config, response: DAVResponse) -> DAVSenderAbc:
        raise NotImplementedError


class TestDAVSenderRaw(BaseTestSender):
    sender_name = b"DAVSenderRaw"

    def get_dav_sender(self, config: Config, response: DAVResponse) -> DAVSenderAbc:
        return DAVSenderRaw(config, response)

    async def test_empty_content(self):
        dav_sender = self.get_dav_sender(Config(), DAVResponse(200))
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        assert fake_send.status == 200
        headers = dict(fake_send.headers)
        assert headers[b"Content-Type"] == b"text/html"
        assert headers[b"Content-Length"] == b"0"
        assert fake_send.trailers is True
        assert fake_send.bodys == [b""]
        assert fake_send.body_content_length == 0

    async def test_have_content(self):
        # have content
        body_content = DECOMPRESS_CONTENT_1
        body_content_lenght = len(body_content)
        config = Config()
        config.compression.enable = False

        dav_sender = self.get_dav_sender(config, DAVResponse(200, content=body_content))
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        assert fake_send.status == 200
        headers = dict(fake_send.headers)
        assert headers[b"Content-Type"] == b"text/html"
        assert headers[b"Content-Length"] == f"{body_content_lenght}".encode()
        assert fake_send.trailers is True
        assert fake_send.bodys != [b""]
        assert fake_send.body_content_length == body_content_lenght

    async def test_have_content_with_content_range(self):
        # have content
        body_content = DECOMPRESS_CONTENT_1
        body_content_lenght = len(body_content)
        config = Config()
        config.compression.enable = False

        dav_sender = self.get_dav_sender(
            config,
            DAVResponse(
                200,
                content=body_content,
                content_range=DAVResponseContentRange(
                    DAVRangeType.RANGE, 0, 100, body_content_lenght
                ),
            ),
        )
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        headers = dict(fake_send.headers)
        assert (
            headers[b"Content-Range"] == f"bytes 0-100/{body_content_lenght}".encode()
        )
        assert headers[b"Content-Length"] == b"101"


class BaseTestCompressionSender(BaseTestSender):
    minimum_magic_block_size: int

    def get_dav_sender(
        self, config: Config, response: DAVResponse
    ) -> DAVSenderCompressionAbc:
        raise NotImplementedError

    def get_decompress_content(self, bodys: list[bytes]) -> bytes:
        raise NotImplementedError

    async def test_empty_content(self):
        dav_sender = self.get_dav_sender(Config(), DAVResponse(200))
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        assert fake_send.status == 200
        headers = dict(fake_send.headers)
        assert headers[b"Content-Type"] == b"text/html"
        assert fake_send.trailers is True
        # --- magic token
        ic(fake_send.bodys)
        assert fake_send.body_content_length >= self.minimum_magic_block_size

    async def base_test_have_content(self, config: Config, body_content: bytes):
        body_content_lenght = len(body_content)

        dav_sender = self.get_dav_sender(config, DAVResponse(200, content=body_content))
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        assert fake_send.status == 200
        headers = dict(fake_send.headers)
        assert headers[b"Content-Type"] == b"text/html"
        assert headers[b"Content-Encoding"] == self.sender_name
        assert b"Content-Length" not in headers
        assert (
            headers[b"X-Uncompressed-Content-Length"]
            == f"{body_content_lenght}".encode()
        )
        assert fake_send.trailers is True
        assert fake_send.bodys != [b""]

        # --- uncompressed content
        decompress_content = self.get_decompress_content(fake_send.bodys)
        assert decompress_content == body_content
        assert len(decompress_content) == body_content_lenght

    def _get_default_config(self) -> Config:
        config = Config()
        config.compression.enable = True
        config.compression.enable_zstd = True
        config.compression.enable_deflate = False
        config.compression.enable_gzip = False

        return config

    async def test_have_content_1_recommend(self):
        config = self._get_default_config()
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_1_fast(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.FAST
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_1_best(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.BEST
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_2_recommend(self):
        config = self._get_default_config()
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_2)

    async def test_have_content_2_fast(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.FAST
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_2)

    async def test_have_content_2_best(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.BEST
        await self.base_test_have_content(config, DECOMPRESS_CONTENT_2)


class TestCompressionSenderZstd(BaseTestCompressionSender):
    sender_name: bytes = b"zstd"
    minimum_magic_block_size: int = 9

    def get_dav_sender(
        self, config: Config, response: DAVResponse
    ) -> DAVSenderCompressionAbc:
        return DAVSenderZstd(config, response)

    def get_decompress_content(self, bodys: list[bytes]) -> bytes:
        decompress_content = b""
        for body in bodys:
            decompress_content += zstd.decompress(body)

        return decompress_content


class TestCompressionSenderDeflate(BaseTestCompressionSender):
    sender_name: bytes = b"deflate"
    minimum_magic_block_size: int = 1

    def get_dav_sender(self, config: Config, response: DAVResponse):
        return DAVSenderDeflate(config, response)

    def get_decompress_content(self, bodys: list[bytes]):
        decompress_content = b""
        for body in bodys:
            decompress_content += zlib.decompress(body)

        return decompress_content


class TestCompressionSenderGzip(BaseTestCompressionSender):
    sender_name: bytes = b"gzip"
    minimum_magic_block_size: int = 1

    def get_dav_sender(self, config: Config, response: DAVResponse):
        return DAVSenderGzip(config, response)

    def get_decompress_content(self, bodys: list[bytes]):
        compressed_data = b""
        for body in bodys:
            compressed_data += body

        decompress_content = gzip.decompress(compressed_data)
        return decompress_content
