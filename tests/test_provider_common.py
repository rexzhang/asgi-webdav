from uuid import uuid4

import pytest

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DAVPath,
    DAVRangeType,
    DAVRequestIf,
    DAVRequestIfCondition,
    DAVRequestIfConditionType,
    DAVRequestRange,
    DAVResponseContentRange,
)
from asgi_webdav.exceptions import DAVCodingError
from asgi_webdav.provider.common import DAVProvider, get_response_content_range

from .kits.lock import (
    HEADER_IF_ETAG1,
    RES_OWNER_1,
    RES_PATH_1,
)

DEFAULT_PREFIX = DAVPath("/prefix")


@pytest.fixture
def dav_provider():
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


def test_DAVProvider_get_dist_path(dav_provider):
    dist_path = DAVPath("/dist_path")
    assert dav_provider.get_dist_path(DEFAULT_PREFIX.add_child(dist_path)) == dist_path


class TestDAVProvider_check_request_ifs_with_res_paths:
    async def test_basic(self, mocker, dav_provider: DAVProvider):
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG1,
        )
        lock_info1 = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)

        assert await dav_provider._check_request_ifs_with_res_paths(
            request_ifs=[
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                str(lock_info1.token),
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
            res_paths=[RES_PATH_1],
        )

        # invalid lock token: not UUID
        assert (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.TOKEN,
                                    "token no UUID",
                                ),
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
            is False
        )

        # invalid lock token: cannot match
        assert (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    False, DAVRequestIfConditionType.TOKEN, str(uuid4())
                                ),
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
            is False
        )

        # miss token
        assert (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
            is False
        )

        # wrong etag
        assert (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.TOKEN,
                                    str(lock_info1.token),
                                ),
                                DAVRequestIfCondition(
                                    False, DAVRequestIfConditionType.ETAG, "wrong etag"
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
            is False
        )
