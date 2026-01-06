from uuid import uuid4

import pytest
from icecream import ic

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
from asgi_webdav.lock import DAVLock
from asgi_webdav.provider.common import DAVProvider, get_response_content_range

from .kits.lock import (
    HEADER_IF_ETAG_1,
    RES_OWNER_1,
    RES_PATH_1,
)

DEFAULT_PREFIX = DAVPath("/prefix")


@pytest.fixture
def dav_provider():
    dav_provider = DAVProvider(
        config=Config(),
        prefix=DEFAULT_PREFIX,
        uri="",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )

    yield dav_provider

    dav_provider.dav_lock = DAVLock()


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
            return_value=HEADER_IF_ETAG_1,
        )
        lock_info1 = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)

        # pass ---
        # check token & etag
        locked, precondition_failed = (
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
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is False

        # check token only
        locked, precondition_failed = (
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
                                )
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is False

        # no pass ---

        # invalid lock token: not UUID
        locked, precondition_failed = (
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
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        ic(locked, precondition_failed)
        assert locked is False
        assert precondition_failed is True

        # invalid lock token: cannot match
        locked, precondition_failed = (
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
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is True
        assert precondition_failed is False

        # miss token
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is True
        assert precondition_failed is False

        # wrong etag
        locked, precondition_failed = (
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
        )
        ic(locked, precondition_failed)
        assert locked is False
        assert precondition_failed is True

    async def test_res_locked_if_empty(self, mocker, dav_provider: DAVProvider):
        """
        - 没有 header If,或者为空
        - 当资源有锁,同时请求的If为空,应该返回 423 Locked
        """
        _ = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)

        ic(dav_provider.dav_lock)
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=list(), res_paths=[RES_PATH_1]
            )
        )
        ic(locked, precondition_failed, dav_provider.dav_lock)
        assert locked is True
        assert precondition_failed is False

    async def test_res_locked_not_no_lock(self, mocker, dav_provider: DAVProvider):
        """If: (<opaquelocktoken:4e597a79-982b-4f94-ba3f-464ea455a61bx>) (Not <DAV:no-lock>)
        - 资源有锁
        - 第一轮条件中的 token 不正确, 需要第二轮通过
        - 第二轮要求 Not <DAV:no-lock>; 即资源不能没有锁
        - 所以应该返回 423
        """
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        res_path=RES_PATH_1,
                        conditions=[
                            [
                                DAVRequestIfCondition(
                                    is_not=False,
                                    type=DAVRequestIfConditionType.TOKEN,
                                    data=f"{str(uuid4())}",  # random token
                                )
                            ],
                            [
                                DAVRequestIfCondition(
                                    is_not=True,
                                    type=DAVRequestIfConditionType.NO_LOCK,
                                    data="",
                                )
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        ic(locked, precondition_failed)
        assert locked is True
        assert precondition_failed is False

        # 现在有锁了, 应该通过检查
        lock_info1 = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        res_path=RES_PATH_1,
                        conditions=[
                            [
                                DAVRequestIfCondition(
                                    is_not=False,
                                    type=DAVRequestIfConditionType.TOKEN,
                                    data=f"{str(lock_info1.token)}",
                                )
                            ],
                            [
                                DAVRequestIfCondition(
                                    is_not=True,
                                    type=DAVRequestIfConditionType.NO_LOCK,
                                    data="",
                                )
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        ic(locked, precondition_failed)
        assert locked is False
        assert precondition_failed is False

    async def test_res_locked_no_lock(self, mocker, dav_provider: DAVProvider):
        """If: (<DAV:no-lock>)
        - <DAV:no-lock> 为不正确的格式,视为条件不匹配,返回 412
        - RFC4918 没有说明是否应该支持还是不支持
        - 理论上应该支持,但是 litmus 似乎刻意地不支持
        """

        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        res_path=RES_PATH_1,
                        conditions=[
                            [
                                DAVRequestIfCondition(
                                    is_not=False,
                                    type=DAVRequestIfConditionType.NO_LOCK,
                                    data="",
                                )
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        ic(locked, precondition_failed)
        assert locked is False
        assert precondition_failed is True

    async def test_etag(self, mocker, dav_provider: DAVProvider):
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG_1,
        )
        lock_info1 = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)

        # pass
        locked, precondition_failed = (
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
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is False

        # 412
        locked, precondition_failed = (
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
                                    False,
                                    DAVRequestIfConditionType.ETAG,
                                    "wrong etag",
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is True

    async def test_not_etag(self, mocker, dav_provider: DAVProvider):
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG_1,
        )
        lock_info1 = await dav_provider.dav_lock.new(RES_OWNER_1, RES_PATH_1)

        # 412
        locked, precondition_failed = (
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
                                    True,
                                    DAVRequestIfConditionType.ETAG,
                                    HEADER_IF_ETAG_1,
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is True

        # pass
        locked, precondition_failed = (
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
                                    True,
                                    DAVRequestIfConditionType.ETAG,
                                    "wrong etag",
                                ),
                            ],
                        ],
                    )
                ],
                res_paths=[RES_PATH_1],
            )
        )
        assert locked is False
        assert precondition_failed is False

    # TODO:!!! rfc4918 examples
