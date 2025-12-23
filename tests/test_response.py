from collections.abc import AsyncGenerator

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH,
    DAVCompressionMethod,
    DAVResponseContentType,
)
from asgi_webdav.response import (
    DAVResponse,
    get_response_body_generator,
)

from .testkit_common import get_all_data_from_response_body_generator

DEFAULT_RESPONSE_CONTENT_BYTES = b"default response bytes"
DEFAULT_RESPONSE_CONTENT_BYTES_LENGTH = len(DEFAULT_RESPONSE_CONTENT_BYTES)

RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML = "text/html"


def get_bytes(length: int = DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH) -> bytes:
    return b"b0" * length


def test_default_response():
    response = DAVResponse(200)

    assert response.status == 200
    assert isinstance(response.headers, dict)

    assert response.content == b""
    assert isinstance(response.content_body_generator, AsyncGenerator)
    assert response.content_length == 0
    assert response.content_range.enable is False

    assert response.response_type == DAVResponseContentType.HTML
    assert response.headers[b"Content-Type"] == b"text/html"


async def test_post_init():
    # content is bytes
    response = DAVResponse(status=200, content=DEFAULT_RESPONSE_CONTENT_BYTES)

    assert response.content == DEFAULT_RESPONSE_CONTENT_BYTES
    assert (
        await get_all_data_from_response_body_generator(response.content_body_generator)
        == DEFAULT_RESPONSE_CONTENT_BYTES
    )
    assert response.content_length == DEFAULT_RESPONSE_CONTENT_BYTES_LENGTH

    # content is DAVResponseBodyGenerator
    response = DAVResponse(
        status=200, content=get_response_body_generator(DEFAULT_RESPONSE_CONTENT_BYTES)
    )
    assert (
        await get_all_data_from_response_body_generator(response.content_body_generator)
        == DEFAULT_RESPONSE_CONTENT_BYTES
    )
    assert response.content_length is None

    # response_type is XML
    response = DAVResponse(status=200, response_type=DAVResponseContentType.XML)
    assert response.headers[b"Content-Type"] == b"application/xml"


def test_can_be_compressed():
    assert DAVResponse._can_be_compressed("text/plain", "")
    assert DAVResponse._can_be_compressed("text/html", "")
    assert DAVResponse._can_be_compressed("text/html; charset=utf-8", "")
    assert DAVResponse._can_be_compressed("dont/compress", "") is False

    assert DAVResponse._can_be_compressed("compress/please", "compress")
    assert DAVResponse._can_be_compressed("compress/please", "decompress") is False


def test_match_compression_method():
    bytes_100 = get_bytes(100)
    bytes_enough_for_compression = get_bytes()

    config = Config()
    response = DAVResponse(200)

    # empty response
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.RAW
    )

    # too small
    response = DAVResponse(200, content=bytes_100)
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.RAW
    )

    # enough for compression
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.ZSTD
    )

    # config.compression.enable == False
    config = Config()
    config.compression.enable = False
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.RAW
    )

    # response.content_range.enable == True
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)
    response.content_range.enable = True
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.RAW
    )

    # content can't compress
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header="	application/zip",
        )
        == DAVCompressionMethod.RAW
    )

    # match request accept encoding
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)

    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip, deflate, br",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.DEFLATE
    )
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="gzip",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.GZIP
    )
    assert (
        response._match_compression_method(
            config=config,
            request_accept_encoding="other",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVCompressionMethod.RAW
    )


def test_process():
    pass
