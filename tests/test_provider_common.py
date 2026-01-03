import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DAVPath,
    DAVRangeType,
    DAVRequestRange,
    DAVResponseContentRange,
)
from asgi_webdav.exceptions import DAVCodingError
from asgi_webdav.provider.common import DAVProvider, get_response_content_range

DEFAULT_PREFIX = DAVPath("/prefix")


@pytest.fixture
def default_dav_provider():
    return DAVProvider(
        config=Config(),
        prefix=DEFAULT_PREFIX,
        uri="",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )


def test_get_response_content_range():
    assert (
        get_response_content_range([DAVRequestRange(DAVRangeType.RANGE, 0, 100)], 1)
        is None
    )


def test_get_response_content_range_range_mode():
    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.RANGE, 0, 100)], 200
    ) == DAVResponseContentRange(DAVRangeType.RANGE, 0, 100, 200)

    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.RANGE, 100, 199)], 200
    ) == DAVResponseContentRange(DAVRangeType.RANGE, 100, 199, 200)

    # out of range
    assert (
        get_response_content_range([DAVRequestRange(DAVRangeType.RANGE, 200, 300)], 200)
        is None
    )
    assert (
        get_response_content_range([DAVRequestRange(DAVRangeType.RANGE, 0, 300)], 200)
        is None
    )

    # start - ?
    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.RANGE, 0, None)], 200
    ) == DAVResponseContentRange(DAVRangeType.RANGE, 0, 199, 200)

    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.RANGE, 100, None)], 200
    ) == DAVResponseContentRange(DAVRangeType.RANGE, 100, 199, 200)

    # out of range
    assert (
        get_response_content_range(
            [DAVRequestRange(DAVRangeType.RANGE, 200, None)], 200
        )
        is None
    )


def test_get_response_content_range_suffix_mode():
    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.SUFFIX, None, None, 200)], 200
    ) == DAVResponseContentRange(DAVRangeType.SUFFIX, 0, 199, 200)

    assert get_response_content_range(
        [DAVRequestRange(DAVRangeType.SUFFIX, None, None, 100)], 200
    ) == DAVResponseContentRange(DAVRangeType.SUFFIX, 100, 199, 200)

    # out of range
    assert (
        get_response_content_range(
            [DAVRequestRange(DAVRangeType.SUFFIX, None, None, 300)], 200
        )
        is None
    )

    # wrong input data
    with pytest.raises(DAVCodingError):
        get_response_content_range([], 200)

    with pytest.raises(DAVCodingError):
        print(
            get_response_content_range(
                [DAVRequestRange(DAVRangeType.RANGE, None, None, 200)], 200
            )
        )


def test_DAVProvider_get_dist_path(default_dav_provider):
    dist_path = DAVPath("/dist_path")
    assert (
        default_dav_provider.get_dist_path(DEFAULT_PREFIX.add_child(dist_path))
        == dist_path
    )
