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
)
from asgi_webdav.response import (
    DAVResponse,
    DAVSenderCompressionAbc,
    DAVSenderDeflate,
    DAVSenderGzip,
    DAVSenderRaw,
    DAVSenderZstd,
)

from .testkit_asgi_v2 import ASGIFakeSend
from .testkit_common import get_bytes, get_generate_random_bytes

DECOMPRESS_CONTENT_1 = get_bytes(DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH)
DECOMPRESS_CONTENT_2 = get_generate_random_bytes(
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH
)


async def test_DAVSenderRaw():
    # empty content
    dav_sender = DAVSenderRaw(Config(), DAVResponse(200))
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

    # have content
    body_content = DECOMPRESS_CONTENT_1
    body_content_lenght = len(body_content)
    config = Config()
    config.compression.enable = False

    dav_sender = DAVSenderRaw(config, DAVResponse(200, content=body_content))
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


class BaseTestCompressionSender:
    minimum_magic_block_size: int

    def _get_dav_sender(
        self, config: Config, response: DAVResponse
    ) -> DAVSenderCompressionAbc:
        raise NotImplementedError

    def _get_decompress_content(self, bodys: list[bytes]) -> bytes:
        raise NotImplementedError

    async def test_empty_content(self):
        dav_sender = self._get_dav_sender(Config(), DAVResponse(200))
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

    async def _test_have_content(self, config: Config, body_content: bytes):
        body_content_lenght = len(body_content)

        dav_sender = self._get_dav_sender(
            config, DAVResponse(200, content=body_content)
        )
        fake_send = ASGIFakeSend()

        await dav_sender.send_it(fake_send)
        ic(fake_send)

        assert fake_send.status == 200
        headers = dict(fake_send.headers)
        assert headers[b"Content-Type"] == b"text/html"
        assert headers[b"Content-Encoding"] == dav_sender.name
        assert b"Content-Length" not in headers
        assert (
            headers[b"X-Uncompressed-Content-Length"]
            == f"{body_content_lenght}".encode()
        )
        assert fake_send.trailers is True
        assert fake_send.bodys != [b""]

        # --- uncompressed content
        decompress_content = self._get_decompress_content(fake_send.bodys)
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
        await self._test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_1_fast(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.FAST
        await self._test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_1_best(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.BEST
        await self._test_have_content(config, DECOMPRESS_CONTENT_1)

    async def test_have_content_2_recommend(self):
        config = self._get_default_config()
        await self._test_have_content(config, DECOMPRESS_CONTENT_2)

    async def test_have_content_2_fast(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.FAST
        await self._test_have_content(config, DECOMPRESS_CONTENT_2)

    async def test_have_content_2_best(self):
        config = self._get_default_config()
        config.compression.level = DAVCompressLevel.BEST
        await self._test_have_content(config, DECOMPRESS_CONTENT_2)


class TestCompressionSenderZstd(BaseTestCompressionSender):
    minimum_magic_block_size: int = 9

    def _get_dav_sender(
        self, config: Config, response: DAVResponse
    ) -> DAVSenderCompressionAbc:
        return DAVSenderZstd(config, response)

    def _get_decompress_content(self, bodys: list[bytes]) -> bytes:
        decompress_content = b""
        for body in bodys:
            decompress_content += zstd.decompress(body)

        return decompress_content


class TestCompressionSenderDeflate(BaseTestCompressionSender):
    minimum_magic_block_size: int = 1

    def _get_dav_sender(self, config: Config, response: DAVResponse):
        return DAVSenderDeflate(config, response)

    def _get_decompress_content(self, bodys: list[bytes]):
        decompress_content = b""
        for body in bodys:
            decompress_content += zlib.decompress(body)

        return decompress_content


class TestCompressionSenderGzip(BaseTestCompressionSender):
    minimum_magic_block_size: int = 1

    def _get_dav_sender(self, config: Config, response: DAVResponse):
        return DAVSenderGzip(config, response)

    def _get_decompress_content(self, bodys: list[bytes]):
        compressed_data = b""
        for body in bodys:
            compressed_data += body

        decompress_content = gzip.decompress(compressed_data)
        return decompress_content
