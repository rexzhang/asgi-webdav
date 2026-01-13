import pytest

from asgi_webdav.constants import DAVDepth
from asgi_webdav.exceptions import DAVRequestParseError
from asgi_webdav.request import (
    _parse_header_accept_encoding,
    _parse_header_depth,
    _parse_header_overwrite,
)


def test_parse_header_depth():
    # default
    assert _parse_header_depth(None) == DAVDepth.ZERO

    # valid
    assert _parse_header_depth(b"0") == DAVDepth.ZERO
    assert _parse_header_depth(b"1") == DAVDepth.ONE
    assert _parse_header_depth(b"infinity") == DAVDepth.INFINITY

    with pytest.raises(DAVRequestParseError):
        _parse_header_depth(b"invalid")


def test_parse_header_overwrite():
    # default
    assert _parse_header_overwrite(None) is True

    # valid
    assert _parse_header_overwrite(b"T") is True
    assert _parse_header_overwrite(b"F") is False

    # invalid
    with pytest.raises(DAVRequestParseError):
        _parse_header_overwrite(b"invalid")


def test_parse_header_accept_encoding():
    # default
    assert _parse_header_accept_encoding(None) == ""

    # valid
    assert (
        _parse_header_accept_encoding(b"gzip, deflate, br, zstd")
        == "gzip, deflate, br, zstd"
    )
