from collections.abc import AsyncGenerator

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DAVMethod,
    DAVRangeType,
    DAVResponseContentRange,
    DAVResponseContentType,
    DAVSenderName,
)
from asgi_webdav.response import (
    DAVResponse,
    DAVResponseMethodNotAllowed,
    DAVSenderDeflate,
    DAVSenderGzip,
    DAVSenderRaw,
    DAVSenderZstd,
    get_dav_sender,
    get_response_body_generator,
)

from .kits.common import (
    get_all_data_from_response_body_generator,
    get_bytes,
    get_generate_random_bytes,
)

DEFAULT_RESPONSE_CONTENT_BYTES = b"default response bytes"
DEFAULT_RESPONSE_CONTENT_BYTES_LENGTH = len(DEFAULT_RESPONSE_CONTENT_BYTES)

RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML = "text/html"

RANDOM_RESPONSE_CONTENT_BYTES_LENGTH = 1000
RANDOM_RESPONSE_CONTENT_BYTES = get_generate_random_bytes(1000)


async def test_get_response_body_generator():
    # empty
    assert (
        await get_all_data_from_response_body_generator(get_response_body_generator())
        == b""
    )

    # short content
    assert (
        await get_all_data_from_response_body_generator(
            get_response_body_generator(DEFAULT_RESPONSE_CONTENT_BYTES)
        )
        == DEFAULT_RESPONSE_CONTENT_BYTES
    )

    # random short content
    data = get_bytes(DEFAULT_RESPONSE_CONTENT_BYTES_LENGTH)
    assert (
        await get_all_data_from_response_body_generator(
            get_response_body_generator(data)
        )
        == data
    )

    # random long content
    assert (
        await get_all_data_from_response_body_generator(
            get_response_body_generator(RANDOM_RESPONSE_CONTENT_BYTES)
        )
        == RANDOM_RESPONSE_CONTENT_BYTES
    )


async def test_get_response_body_generator_with_range():
    block_size = int(RANDOM_RESPONSE_CONTENT_BYTES_LENGTH / 10)

    # start - end
    range_start = int(RANDOM_RESPONSE_CONTENT_BYTES_LENGTH / 4)
    range_end = int(RANDOM_RESPONSE_CONTENT_BYTES_LENGTH / 2)

    result = await get_all_data_from_response_body_generator(
        get_response_body_generator(
            RANDOM_RESPONSE_CONTENT_BYTES,
            content_range_start=range_start,
            content_range_end=range_end,
            block_size=block_size,
        )
    )
    assert result == RANDOM_RESPONSE_CONTENT_BYTES[range_start : range_end + 1]
    assert len(result) == range_end - range_start + 1

    # start -
    # range_start = int(RANDOM_RESPONSE_CONTENT_BYTES_LENGTH / 4)
    range_start = 0
    range_end = None
    result = await get_all_data_from_response_body_generator(
        get_response_body_generator(
            RANDOM_RESPONSE_CONTENT_BYTES,
            content_range_start=range_start,
            content_range_end=range_end,
            block_size=block_size,
        )
    )
    print(range_start, range_end, len(result))
    assert result == RANDOM_RESPONSE_CONTENT_BYTES[range_start:]
    assert len(result) == RANDOM_RESPONSE_CONTENT_BYTES_LENGTH - range_start

    range_start = 1
    range_end = None
    result = await get_all_data_from_response_body_generator(
        get_response_body_generator(
            RANDOM_RESPONSE_CONTENT_BYTES,
            content_range_start=range_start,
            content_range_end=range_end,
            block_size=block_size,
        )
    )
    print(range_start, range_end, len(result))
    assert result == RANDOM_RESPONSE_CONTENT_BYTES[range_start:]
    assert len(result) == RANDOM_RESPONSE_CONTENT_BYTES_LENGTH - range_start

    # - end
    range_start = None
    range_end = RANDOM_RESPONSE_CONTENT_BYTES_LENGTH - 1
    result = await get_all_data_from_response_body_generator(
        get_response_body_generator(
            RANDOM_RESPONSE_CONTENT_BYTES,
            content_range_start=range_start,
            content_range_end=range_end,
            block_size=block_size,
        )
    )
    assert result == RANDOM_RESPONSE_CONTENT_BYTES[: range_end + 1]
    assert len(result) == RANDOM_RESPONSE_CONTENT_BYTES_LENGTH


def test_default_response():
    response = DAVResponse(200)

    assert response.status == 200
    assert isinstance(response.headers, dict)

    assert response.content == b""
    assert isinstance(response.content_body_generator, AsyncGenerator)
    assert response.content_length == 0
    assert response.content_range is None

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
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.RAW
    )

    # too small
    response = DAVResponse(200, content=bytes_100)
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.RAW
    )

    # enough for compression
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.ZSTD
    )

    # config.compression.enable == False
    config = Config()
    config.compression.enable = False
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.RAW
    )

    # response.content_range is not None
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)
    response.content_range = DAVResponseContentRange(DAVRangeType.RANGE, 0, 100, 200)
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.RAW
    )

    # content can't compress
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br, zstd",
            response_content_type_from_header="	application/zip",
        )
        == DAVSenderName.RAW
    )

    # match request accept encoding
    config = Config()
    response = DAVResponse(200, content=bytes_enough_for_compression)

    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip, deflate, br",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.DEFLATE
    )
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="gzip",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.GZIP
    )
    assert (
        response._match_dav_sender(
            config=config,
            request_accept_encoding="other",
            response_content_type_from_header=RESPONSE_HEADER_CONTENT_TYPE_TEXT_HTML,
        )
        == DAVSenderName.RAW
    )


def test_get_dav_sender():
    config = Config()
    response = DAVResponse(200)

    response.matched_sender_name = DAVSenderName.ZSTD
    dav_sender = get_dav_sender(config, response)
    assert dav_sender.name == DAVSenderZstd.name

    response.matched_sender_name = DAVSenderName.DEFLATE
    dav_sender = get_dav_sender(config, response)
    assert dav_sender.name == DAVSenderDeflate.name

    response.matched_sender_name = DAVSenderName.GZIP
    dav_sender = get_dav_sender(config, response)
    assert dav_sender.name == DAVSenderGzip.name

    response.matched_sender_name = DAVSenderName.RAW
    dav_sender = get_dav_sender(config, response)
    assert dav_sender.name == DAVSenderRaw.name


def test_DAVResponseMethodNotAllowed():
    response = DAVResponseMethodNotAllowed(DAVMethod.GET)
    assert response.status == 405
    assert response.content == b"method:GET is not support method"
