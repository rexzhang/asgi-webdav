from icecream import ic

from asgi_webdav.constants import DAVRangeType
from asgi_webdav.request import DAVRequestIfRange, _parse_header_range


def test_DAVRequestIfRange():
    etag = 'W/"aec2d98e33b04a06a67a292f66337302"'
    last_modified = "Wed, 21 Oct 2015 07:28:00 GMT"

    # empty
    if_range = DAVRequestIfRange(b"")
    assert if_range.etag == ""
    assert if_range.last_modified == ""

    # etag
    if_range = DAVRequestIfRange(etag.encode())
    assert if_range.etag == etag
    assert if_range.last_modified == ""

    # last_modified
    if_range = DAVRequestIfRange(last_modified.encode())
    assert if_range.etag == ""
    assert if_range.last_modified == last_modified

    # match
    if_range = DAVRequestIfRange(etag.encode())
    ic(if_range)
    assert if_range.match(etag=etag, last_modified="") is True
    assert if_range.match(etag="", last_modified=last_modified) is False
    assert if_range.match(etag="", last_modified="") is False

    if_range = DAVRequestIfRange(last_modified.encode())
    ic(if_range)
    assert if_range.match(etag="", last_modified=last_modified) is True
    assert if_range.match(etag=etag, last_modified="") is False
    assert if_range.match(etag="", last_modified="") is False


def test_parser_header_range():
    # empty
    ranges = _parse_header_range(b"")
    assert len(ranges) == 0

    # empty ranges
    ranges = _parse_header_range(b"bytes=")
    assert len(ranges) == 0

    # wrong unit
    ranges = _parse_header_range(b"bads=200-1000")
    assert len(ranges) == 0


def test_parser_header_range_range_mode():
    # success
    ranges = _parse_header_range(b"bytes=0-1000")
    assert len(ranges) == 1

    ranges = _parse_header_range(b"bytes=200-1000")
    assert ranges[0].type == DAVRangeType.RANGE
    assert ranges[0].range_start == 200
    assert ranges[0].range_end == 1000
    assert ranges[0].suffix_length is None

    ranges = _parse_header_range(b"bytes=0-")
    assert len(ranges) == 1

    ranges = _parse_header_range(b"bytes=200-")
    assert ranges[0].type == DAVRangeType.RANGE
    assert ranges[0].range_start == 200
    assert ranges[0].range_end is None
    assert ranges[0].suffix_length is None

    ranges = _parse_header_range(b"bytes=200-1000, 2000-6576, 19000-")
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
    ranges = _parse_header_range(b"bytes=1000-1000")
    assert len(ranges) == 0  # TODO rasie exception

    ranges = _parse_header_range(b"bytes=bad-1000")
    assert len(ranges) == 1  # TODO rasie exception

    ranges = _parse_header_range(b"bytes=100-bad2")
    assert len(ranges) == 1  # TODO rasie exception

    ranges = _parse_header_range(b"bytes=bad-bad2")
    assert len(ranges) == 0
    ranges = _parse_header_range(b"bytes=-")
    assert len(ranges) == 0
    ranges = _parse_header_range(b"bytes=abcd")
    assert len(ranges) == 0


def test_parser_header_range_suffix_mode():
    # success
    ranges = _parse_header_range(b"bytes=-1000")
    assert ranges[0].type == DAVRangeType.SUFFIX
    assert ranges[0].range_start is None
    assert ranges[0].range_end is None
    assert ranges[0].suffix_length == 1000

    # fail
    ranges = _parse_header_range(b"bytes=-0")
    assert len(ranges) == 0

    ranges = _parse_header_range(b"bytes=-bad")
    assert len(ranges) == 0

    ranges = _parse_header_range(b"bytes=-100, 100-1000")
    assert len(ranges) == 0  # TODO rasie exception

    ranges = _parse_header_range(b"bytes=100-1000, -2000")
    assert len(ranges) == 0  # TODO rasie exception
