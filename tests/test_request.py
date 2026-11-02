import pytest

from asgi_webdav.constants import DAVDepth
from asgi_webdav.exceptions import DAVRequestParseError
from asgi_webdav.request import (
    _parse_header_accept_encoding,
    _parse_header_depth,
    _parse_header_overwrite,
)

from .kits.asgi import create_dav_request_object


def test_parse_header_depth() -> None:
    # default
    assert _parse_header_depth(None) == DAVDepth.ZERO

    # valid
    assert _parse_header_depth(b"0") == DAVDepth.ZERO
    assert _parse_header_depth(b"1") == DAVDepth.ONE
    assert _parse_header_depth(b"infinity") == DAVDepth.INFINITY

    with pytest.raises(DAVRequestParseError):
        _parse_header_depth(b"invalid")


def test_parse_header_overwrite() -> None:
    # default
    assert _parse_header_overwrite(None) is True

    # valid
    assert _parse_header_overwrite(b"T") is True
    assert _parse_header_overwrite(b"F") is False

    # invalid
    with pytest.raises(DAVRequestParseError):
        _parse_header_overwrite(b"invalid")


def test_parse_header_accept_encoding() -> None:
    # default
    assert _parse_header_accept_encoding(None) == ""

    # valid
    assert (
        _parse_header_accept_encoding(b"gzip, deflate, br, zstd")
        == "gzip, deflate, br, zstd"
    )


@pytest.mark.asyncio
async def test_parser_body_propfind_encoding_routes_to_extra() -> None:
    # DAV:encoding is not a DAV_PROPERTY_BASIC_KEYS member: a named request
    # routes it through the extra-property path
    request = create_dav_request_object(method="PROPFIND", path="/")
    request.body = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<D:propfind xmlns:D="DAV:"><D:prop>'
        b"<D:displayname/><D:encoding/>"
        b"</D:prop></D:propfind>"
    )

    assert await request._parser_body_propfind() is True

    assert request.propfind_fetch_all_property is False
    assert request.propfind_basic_keys == {"displayname"}
    assert request.propfind_extra_keys == [("DAV:", "encoding")]
    assert request.propfind_only_fetch_basic is False
