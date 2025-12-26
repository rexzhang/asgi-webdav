from asgi_webdav.constants import DAVRangeType
from asgi_webdav.request import _parser_header_range


def test_parser_header_range():
    # empty
    ranges = _parser_header_range(b"")
    assert len(ranges) == 0

    # empty ranges
    ranges = _parser_header_range(b"bytes=")
    assert len(ranges) == 0

    # wrong unit
    ranges = _parser_header_range(b"bads=200-1000")
    assert len(ranges) == 0


def test_parser_header_range_range_mode():
    # success
    ranges = _parser_header_range(b"bytes=0-1000")
    assert len(ranges) == 1

    ranges = _parser_header_range(b"bytes=200-1000")
    assert ranges[0].type == DAVRangeType.RANGE
    assert ranges[0].range_start == 200
    assert ranges[0].range_end == 1000
    assert ranges[0].suffix_length is None

    ranges = _parser_header_range(b"bytes=0-")
    assert len(ranges) == 1

    ranges = _parser_header_range(b"bytes=200-")
    assert ranges[0].type == DAVRangeType.RANGE
    assert ranges[0].range_start == 200
    assert ranges[0].range_end is None
    assert ranges[0].suffix_length is None

    ranges = _parser_header_range(b"bytes=200-1000, 2000-6576, 19000-")
    assert len(ranges) == 3
    assert ranges[0].type == DAVRangeType.RANGE
    assert ranges[0].range_start == 200
    assert ranges[0].range_end == 1000
    assert ranges[0].suffix_length is None

    assert ranges[1].type == DAVRangeType.RANGE
    assert ranges[1].range_start == 2000
    assert ranges[1].range_end == 6576
    assert ranges[1].suffix_length is None

    assert ranges[2].type == DAVRangeType.RANGE
    assert ranges[2].range_start == 19000
    assert ranges[2].range_end is None
    assert ranges[2].suffix_length is None

    # fail
    ranges = _parser_header_range(b"bytes=1000-1000")
    assert len(ranges) == 0  # TODO rasie exception

    ranges = _parser_header_range(b"bytes=bad-1000")
    assert len(ranges) == 1  # TODO rasie exception

    ranges = _parser_header_range(b"bytes=100-bad2")
    assert len(ranges) == 1  # TODO rasie exception

    ranges = _parser_header_range(b"bytes=bad-bad2")
    assert len(ranges) == 0
    ranges = _parser_header_range(b"bytes=-")
    assert len(ranges) == 0
    ranges = _parser_header_range(b"bytes=abcd")
    assert len(ranges) == 0


def test_parser_header_range_suffix_mode():
    # success
    ranges = _parser_header_range(b"bytes=-1000")
    assert ranges[0].type == DAVRangeType.SUFFIX
    assert ranges[0].range_start is None
    assert ranges[0].range_end is None
    assert ranges[0].suffix_length == 1000

    # fail
    ranges = _parser_header_range(b"bytes=-0")
    assert len(ranges) == 0

    ranges = _parser_header_range(b"bytes=-bad")
    assert len(ranges) == 0

    ranges = _parser_header_range(b"bytes=-100, 100-1000")
    assert len(ranges) == 0  # TODO rasie exception

    ranges = _parser_header_range(b"bytes=100-1000, -2000")
    assert len(ranges) == 0  # TODO rasie exception
