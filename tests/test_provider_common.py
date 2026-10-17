from collections.abc import Generator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from asgiref.typing import ASGIReceiveEvent
from icecream import ic
from pytest_mock import MockerFixture

from asgi_webdav.config import Config
from asgi_webdav.constants import (
    DAVLockScope,
    DAVPath,
    DAVRangeType,
    DAVRequestBodyLock,
    DAVRequestIf,
    DAVRequestIfCondition,
    DAVRequestIfConditionType,
    DAVRequestRange,
    DAVResponseContentRange,
    DAVTime,
)
from asgi_webdav.exceptions import DAVCodingError, DAVException
from asgi_webdav.lock import DAVLockKeeper
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.common import DAVProvider, get_response_content_range

from .kits.asgi import create_dav_request_object
from .kits.lock import (
    HEADER_IF_ETAG_1,
    RES_OWNER_1,
    RES_PATH_1,
    RES_PATH_2,
)

DEFAULT_PREFIX = DAVPath("/prefix")


@pytest.fixture
def dav_provider() -> Generator[DAVProvider, None, None]:
    dav_provider = DAVProvider(
        config=Config(),
        prefix=DEFAULT_PREFIX,
        uri="",
        home_dir=False,
        read_only=False,
        ignore_property_extra=False,
    )

    yield dav_provider

    dav_provider.lock_keeper = DAVLockKeeper()


def test_get_response_content_range() -> None:
    assert (
        get_response_content_range([DAVRequestRange(DAVRangeType.RANGE, 0, 100)], 1)
        is None
    )


def test_get_response_content_range_range_mode() -> None:
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


def test_get_response_content_range_suffix_mode() -> None:
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


def test_DAVProvider_get_dist_path(dav_provider: DAVProvider) -> None:
    dist_path = DAVPath("/dist_path")
    assert dav_provider.get_dist_path(DEFAULT_PREFIX.add_child(dist_path)) == dist_path


class TestDAVProvider_check_request_ifs_with_res_paths:
    async def test_basic(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG_1,
        )
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None

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
                                    str(lock_obj1.token),
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
                                    str(lock_obj1.token),
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
                                    "token not UUID",
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

        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=[
                    DAVRequestIf(
                        RES_PATH_1,
                        [
                            [
                                DAVRequestIfCondition(
                                    True,
                                    DAVRequestIfConditionType.TOKEN,
                                    "token not UUID",
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
                                    str(lock_obj1.token),
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

    async def test_res_locked_if_empty(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        """
        - 没有 header If,或者为空
        - 当资源有锁,同时请求的If为空,应该返回 423 Locked
        """
        _ = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)

        ic(dav_provider.lock_keeper)
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=list(), res_paths=[RES_PATH_1]
            )
        )
        ic(locked, precondition_failed, dav_provider.lock_keeper)
        assert locked is True
        assert precondition_failed is False

    async def test_res_locked_not_no_lock(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
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
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None
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
                                    data=f"{str(lock_obj1.token)}",
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

    async def test_res_locked_no_lock(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
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

    async def test_etag(self, mocker: MockerFixture, dav_provider: DAVProvider) -> None:
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG_1,
        )
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None

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
                                    str(lock_obj1.token),
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
                                    str(lock_obj1.token),
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

    async def test_not_etag(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value=HEADER_IF_ETAG_1,
        )
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None

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
                                    str(lock_obj1.token),
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
                                    str(lock_obj1.token),
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

    async def test_rfc4918_example_10_4_6(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.6
        # 10.4.6.  Example - No-tag Production
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None
        request_ifs = [
            DAVRequestIf(
                RES_PATH_1,
                [
                    [
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),
                        ),
                        DAVRequestIfCondition(
                            False, DAVRequestIfConditionType.ETAG, '"I am an ETag"'
                        ),
                    ],
                    [
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.ETAG,
                            '"I am another ETag"',
                        ),
                    ],
                ],
            )
        ]

        # 1
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='"I am an ETag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

        # cleanup
        mocker.stopall()

        # 2
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='"I am another ETag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

        # cleanup
        mocker.stopall()

        # fail
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='"wrong etag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is True

    async def test_rfc4918_example_10_4_7(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.7
        # 10.4.7.  Example - Using "Not" with No-tag Production
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None
        lock_obj2 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_2)
        assert lock_obj2 is not None

        # failed
        request_ifs = [
            DAVRequestIf(
                RES_PATH_1,
                [
                    [
                        DAVRequestIfCondition(
                            True,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),  # 被其锁定
                        ),
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),
                        ),
                    ],
                ],
            )
        ]

        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is True
        assert precondition_failed is False

        # pass
        request_ifs = [
            DAVRequestIf(
                RES_PATH_1,
                [
                    [
                        DAVRequestIfCondition(
                            True,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj2.token),  # 未被其锁定
                        ),
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),
                        ),
                    ],
                ],
            )
        ]

        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

    async def test_rfc4918_example_10_4_8(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.8
        # 10.4.8.  Example - Causing a Condition to Always Evaluate to True

        # 没有锁,失败
        request_ifs = [
            DAVRequestIf(
                RES_PATH_1,
                [
                    [
                        DAVRequestIfCondition(
                            True, DAVRequestIfConditionType.NO_LOCK, ""
                        ),
                    ],
                ],
            )
        ]
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is True
        assert precondition_failed is False

        # pass
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None
        request_ifs = [
            DAVRequestIf(
                RES_PATH_1,
                [
                    [
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),
                        ),
                    ],
                    [
                        DAVRequestIfCondition(
                            True, DAVRequestIfConditionType.NO_LOCK, ""
                        ),
                    ],
                ],
            )
        ]
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

    async def test_rfc4918_example_10_4_9(
        self, mocker: MockerFixture, dav_provider: DAVProvider
    ) -> None:
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.9
        # 10.4.9.  Example - Tagged List If Header in COPY
        lock_obj1 = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
        assert lock_obj1 is not None

        request_ifs = [
            DAVRequestIf(
                DAVPath("/resource1"),
                [
                    [
                        DAVRequestIfCondition(
                            False,
                            DAVRequestIfConditionType.TOKEN,
                            str(lock_obj1.token),
                        ),
                        DAVRequestIfCondition(
                            False, DAVRequestIfConditionType.ETAG, 'W/"A weak ETag"'
                        ),
                    ],
                    [
                        DAVRequestIfCondition(
                            False, DAVRequestIfConditionType.ETAG, '"strong ETag"'
                        ),
                    ],
                ],
            )
        ]

        # pass 1
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='W/"A weak ETag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

        # cleanup
        mocker.stopall()

        # pass 2
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='"strong ETag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is False

        # cleanup
        mocker.stopall()

        # fail
        mocker.patch(
            "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
            return_value='"wrong etag"',
        )
        locked, precondition_failed = (
            await dav_provider._check_request_ifs_with_res_paths(
                request_ifs=request_ifs, res_paths=[RES_PATH_1]
            )
        )
        assert locked is False
        assert precondition_failed is True

    # 10.4.10.  Example - Matching Lock Tokens with Collection Locks
    # 10.4.11.  Example - Matching ETags on Unmapped URLs
    # 这两个需要从更前端的入口开始测试才有意义，所以这里略过


def test_provider_home_dir_not_supported() -> None:
    class NoHomeDirProvider(DAVProvider):
        type = "test"

    with pytest.raises(DAVException):
        NoHomeDirProvider(
            config=Config(),
            prefix=DEFAULT_PREFIX,
            uri="",
            home_dir=True,
            read_only=False,
            ignore_property_extra=False,
        )


async def test_get_res_etag_from_res_path_delegates(
    mocker: MockerFixture, dav_provider: DAVProvider
) -> None:
    mock = mocker.patch(
        "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_dist_path",
        new_callable=AsyncMock,
        return_value='"etag"',
    )
    # the delegate receives the provider-relative path (prefix stripped)
    full_path = DEFAULT_PREFIX.add_child(RES_PATH_1)
    assert await dav_provider._get_res_etag_from_res_path(full_path) == '"etag"'
    mock.assert_awaited_once_with(RES_PATH_1, None)


def test_create_ns_key_with_id() -> None:
    ns_map: dict[str, str] = {}

    assert DAVProvider._create_ns_key_with_id(ns_map, "", "key") == "key"

    assert DAVProvider._create_ns_key_with_id(ns_map, "http://ns-a", "k1") == "ns1:k1"
    assert DAVProvider._create_ns_key_with_id(ns_map, "http://ns-a", "k2") == "ns1:k2"
    assert DAVProvider._create_ns_key_with_id(ns_map, "http://ns-b", "k3") == "ns2:k3"


def make_dav_property(href_path: DAVPath, is_collection: bool) -> DAVProperty:
    return DAVProperty(
        href_path=href_path,
        is_collection=is_collection,
        basic_data=DAVPropertyBasicData(
            is_collection=is_collection,
            display_name=href_path.name,
            creation_date=DAVTime(),
            last_modified=DAVTime(),
            content_length=0 if is_collection else 10,
        ),
        extra_data={("http://example.com/ns", "author"): "tester"},
        extra_not_found=[("http://example.com/ns", "missing")],
    )


@pytest.mark.asyncio
async def test_create_propfind_response(dav_provider: DAVProvider) -> None:
    locked_file = DEFAULT_PREFIX.add_child("locked-file")
    free_file = DEFAULT_PREFIX.add_child("free-file")
    locked_dir = DEFAULT_PREFIX.add_child("locked-dir")

    lock_obj = await dav_provider.lock_keeper.new(RES_OWNER_1, locked_file)
    assert lock_obj is not None

    request = create_dav_request_object(method="PROPFIND", path=locked_file.raw)

    # fetch_all_property covers the union branch of basic keys
    request.propfind_fetch_all_property = True
    result = await dav_provider.create_propfind_response(
        request,
        {
            locked_file: make_dav_property(locked_file, False),
            free_file: make_dav_property(free_file, False),
            locked_dir: make_dav_property(locked_dir, True),
        },
    )
    assert b"200 OK" in result
    assert b"404 Not Found" in result
    assert b"/prefix/locked-file" in result
    assert b"lockdiscovery" in result
    assert b"ns1:author" in result
    assert b"ns1:missing" in result
    assert b"D:collection" in result

    # the request-keys branch of the basic keys selection
    request.propfind_fetch_all_property = False
    request.propfind_basic_keys = {"displayname"}
    result = await dav_provider.create_propfind_response(
        request, {free_file: make_dav_property(free_file, False)}
    )
    assert b"200 OK" in result


@pytest.mark.asyncio
async def test_do_proppatch_success(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="PROPPATCH", path=RES_PATH_1.raw)
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("DAV:", "author"), "tester", True)]
    request.lock_ifs = []

    dav_provider._do_proppatch = AsyncMock(  # type: ignore[method-assign]
        return_value=207
    )

    response = await dav_provider.do_proppatch(request)

    assert response.status == 207
    content = response.content
    assert isinstance(content, bytes)
    assert b"D:multistatus" in content
    assert b"200 OK" in content


@pytest.mark.asyncio
async def test_do_proppatch_locked(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="PROPPATCH", path=RES_PATH_1.raw)
    request.body_is_parsed_success = True
    request.lock_ifs = []

    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)

    response = await dav_provider.do_proppatch(request)

    assert response.status == 423


@pytest.mark.asyncio
async def test_do_proppatch_body_not_parsed(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="PROPPATCH", path=RES_PATH_1.raw)
    request.body_is_parsed_success = False
    request.lock_ifs = []

    response = await dav_provider.do_proppatch(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_do_put_gates(dav_provider: DAVProvider, mocker: MockerFixture) -> None:
    # locked resource, request carries no If header -> 423
    request = create_dav_request_object(method="PUT", path=RES_PATH_1.raw)
    request.lock_ifs = []
    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    response = await dav_provider.do_put(request)
    assert response.status == 423

    # failed precondition (wrong etag on a locked resource) -> 412
    mocker.patch(
        "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
        return_value=HEADER_IF_ETAG_1,
    )
    request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False, DAVRequestIfConditionType.ETAG, "wrong etag"
                    ),
                ],
            ],
        )
    ]
    response = await dav_provider.do_put(request)
    assert response.status == 412


@pytest.mark.asyncio
async def test_do_delete_locked(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="DELETE", path=RES_PATH_1.raw)
    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)

    response = await dav_provider.do_delete(request)

    assert response.status == 423


@pytest.mark.asyncio
async def test_do_copy_gates(dav_provider: DAVProvider) -> None:
    dst = DEFAULT_PREFIX.add_child("copy-dst")

    # miss destination
    request = create_dav_request_object(method="COPY", path=RES_PATH_1.raw)
    response = await dav_provider.do_copy(request)
    assert response.status == 400

    # destination outside the provider prefix
    request.dst_path = DAVPath("/outside/dst")
    response = await dav_provider.do_copy(request)
    assert response.status == 400

    # destination locked, request carries no If header -> 423
    request.dst_path = dst
    request.lock_ifs = []
    await dav_provider.lock_keeper.new(RES_OWNER_1, dst)
    response = await dav_provider.do_copy(request)
    assert response.status == 423


@pytest.mark.asyncio
async def test_do_move_gates(dav_provider: DAVProvider, mocker: MockerFixture) -> None:
    # miss destination
    request = create_dav_request_object(method="MOVE", path=RES_PATH_1.raw)
    response = await dav_provider.do_move(request)
    assert response.status == 400

    # destination outside the provider prefix
    request.dst_path = DAVPath("/outside/dst")
    response = await dav_provider.do_move(request)
    assert response.status == 400

    # source locked, request carries no If header -> 423
    request.dst_path = DEFAULT_PREFIX.add_child("move-dst")
    request.lock_ifs = []
    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    response = await dav_provider.do_move(request)
    assert response.status == 423

    # failed precondition (wrong etag on the source) -> 423 in MOVE
    mocker.patch(
        "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
        return_value=HEADER_IF_ETAG_1,
    )
    request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False, DAVRequestIfConditionType.ETAG, "wrong etag"
                    ),
                ],
            ],
        )
    ]
    response = await dav_provider.do_move(request)
    assert response.status == 423


@pytest.mark.asyncio
async def test_do_lock_new_201(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_1.raw,
        headers={"timeout": "Second-600"},
    )
    request.lock_ifs = []
    request.body_lock = DAVRequestBodyLock(
        scope=DAVLockScope.EXCLUSIVE, owner=RES_OWNER_1
    )

    response = await dav_provider.do_lock(request)

    assert response.status == 201
    assert b"opaquelocktoken:" in response.headers[b"Lock-Token"]
    content = response.content
    assert isinstance(content, bytes)
    assert b"lockdiscovery" in content


@pytest.mark.asyncio
async def test_do_lock_existing_path_200(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_1.raw,
        headers={"timeout": "Second-600"},
    )
    request.lock_ifs = []
    request.body_lock = DAVRequestBodyLock(scope=DAVLockScope.SHARED, owner=RES_OWNER_1)

    assert (await dav_provider.do_lock(request)).status == 201
    # a second lock on the same path takes the refresh-style 200 branch
    assert (await dav_provider.do_lock(request)).status == 200


@pytest.mark.asyncio
async def test_do_lock_conflict_423(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_1.raw,
        headers={"timeout": "Second-600"},
    )
    request.lock_ifs = []
    request.body_lock = DAVRequestBodyLock(
        scope=DAVLockScope.EXCLUSIVE, owner=RES_OWNER_1
    )

    assert (await dav_provider.do_lock(request)).status == 201
    # exclusive lock already held on the path -> keeper.new returns None
    assert (await dav_provider.do_lock(request)).status == 423


@pytest.mark.asyncio
async def test_do_lock_missing_body_412(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="LOCK", path=RES_PATH_1.raw)
    request.lock_ifs = []
    request.body_lock = None

    response = await dav_provider.do_lock(request)

    assert response.status == 412


@pytest.mark.asyncio
async def test_do_lock_depth_412(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_1.raw,
        headers={"timeout": "Second-600", "depth": "1"},
    )
    request.lock_ifs = []
    request.body_lock = DAVRequestBodyLock(
        scope=DAVLockScope.EXCLUSIVE, owner=RES_OWNER_1
    )

    response = await dav_provider.do_lock(request)

    assert response.status == 412


@pytest.mark.asyncio
async def test_do_lock_refresh_200(dav_provider: DAVProvider) -> None:
    lock_obj = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    assert lock_obj is not None

    refresh_request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_1.raw,
        headers={"timeout": "Second-1200"},
    )
    refresh_request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False,
                        DAVRequestIfConditionType.TOKEN,
                        str(lock_obj.token),
                    ),
                ],
            ],
        )
    ]

    response = await dav_provider.do_lock(refresh_request)

    assert response.status == 200
    assert (
        response.headers[b"Lock-Token"] == f"opaquelocktoken:{lock_obj.token}".encode()
    )


@pytest.mark.asyncio
async def test_do_lock_refresh_token_not_found_412(
    dav_provider: DAVProvider,
) -> None:
    refresh_request = create_dav_request_object(
        method="LOCK", path=RES_PATH_1.raw, headers={"timeout": "Second-600"}
    )
    refresh_request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False,
                        DAVRequestIfConditionType.TOKEN,
                        str(uuid4()),
                    ),
                ],
            ],
        )
    ]

    response = await dav_provider.do_lock(refresh_request)

    assert response.status == 412


@pytest.mark.asyncio
async def test_do_lock_bad_token_412(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="LOCK", path=RES_PATH_1.raw)
    request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False, DAVRequestIfConditionType.TOKEN, "token not UUID"
                    ),
                ],
            ],
        )
    ]
    request.body_lock = DAVRequestBodyLock(
        scope=DAVLockScope.EXCLUSIVE, owner=RES_OWNER_1
    )

    response = await dav_provider.do_lock(request)

    assert response.status == 412


@pytest.mark.asyncio
async def test_do_unlock_gates(dav_provider: DAVProvider) -> None:
    # miss token header -> 400
    request = create_dav_request_object(method="UNLOCK", path=RES_PATH_1.raw)
    response = await dav_provider.do_unlock(request)
    assert response.status == 400

    # token not found -> 403
    request = create_dav_request_object(
        method="UNLOCK",
        path=RES_PATH_1.raw,
        headers={
            "lock-token": "<opaquelocktoken:00000000-0000-4000-8000-000000000000>"
        },
    )
    response = await dav_provider.do_unlock(request)
    assert response.status == 403

    # token path mismatch -> 403
    lock_obj = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    assert lock_obj is not None
    request = create_dav_request_object(
        method="UNLOCK",
        path=RES_PATH_2.raw,
        headers={"lock-token": f"<opaquelocktoken:{lock_obj.token}>"},
    )
    response = await dav_provider.do_unlock(request)
    assert response.status == 403

    # release -> 204
    request = create_dav_request_object(
        method="UNLOCK",
        path=RES_PATH_1.raw,
        headers={"lock-token": f"<opaquelocktoken:{lock_obj.token}>"},
    )
    response = await dav_provider.do_unlock(request)
    assert response.status == 204


@pytest.mark.asyncio
async def test_do_proppatch_precondition_412(
    dav_provider: DAVProvider, mocker: MockerFixture
) -> None:
    mocker.patch(
        "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
        return_value=HEADER_IF_ETAG_1,
    )
    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)

    request = create_dav_request_object(method="PROPPATCH", path=RES_PATH_1.raw)
    request.body_is_parsed_success = True
    request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False, DAVRequestIfConditionType.ETAG, "wrong etag"
                    ),
                ],
            ],
        )
    ]

    response = await dav_provider.do_proppatch(request)

    assert response.status == 412


@pytest.mark.asyncio
async def test_do_proppatch_non_207_empty_body(dav_provider: DAVProvider) -> None:
    request = create_dav_request_object(method="PROPPATCH", path=RES_PATH_1.raw)
    request.body_is_parsed_success = True
    request.proppatch_entries = [(("DAV:", "author"), "tester", True)]
    request.lock_ifs = []

    dav_provider._do_proppatch = AsyncMock(return_value=200)  # type: ignore[method-assign]

    response = await dav_provider.do_proppatch(request)

    assert response.status == 200
    assert response.content == b""


@pytest.mark.asyncio
async def test_do_copy_precondition_423(
    dav_provider: DAVProvider, mocker: MockerFixture
) -> None:
    mocker.patch(
        "asgi_webdav.provider.common.DAVProvider._get_res_etag_from_res_path",
        return_value=HEADER_IF_ETAG_1,
    )
    await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)

    request = create_dav_request_object(method="COPY", path=RES_PATH_1.raw)
    request.dst_path = DEFAULT_PREFIX.add_child("copy-dst")
    request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False, DAVRequestIfConditionType.ETAG, "wrong etag"
                    ),
                ],
            ],
        )
    ]

    response = await dav_provider.do_copy(request)

    assert response.status == 423


@pytest.mark.asyncio
async def test_do_lock_refresh_path_mismatch_423(dav_provider: DAVProvider) -> None:
    lock_obj = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    assert lock_obj is not None

    refresh_request = create_dav_request_object(
        method="LOCK",
        path=RES_PATH_2.raw,
        headers={"timeout": "Second-600"},
    )
    refresh_request.lock_ifs = [
        DAVRequestIf(
            RES_PATH_1,
            [
                [
                    DAVRequestIfCondition(
                        False,
                        DAVRequestIfConditionType.TOKEN,
                        str(lock_obj.token),
                    ),
                ],
            ],
        )
    ]

    response = await dav_provider.do_lock(refresh_request)

    assert response.status == 423


@pytest.mark.asyncio
async def test_do_unlock_release_failure_400(
    dav_provider: DAVProvider, mocker: MockerFixture
) -> None:
    lock_obj = await dav_provider.lock_keeper.new(RES_OWNER_1, RES_PATH_1)
    assert lock_obj is not None

    mocker.patch.object(
        dav_provider.lock_keeper, "release", AsyncMock(return_value=False)
    )
    request = create_dav_request_object(
        method="UNLOCK",
        path=RES_PATH_1.raw,
        headers={"lock-token": f"<opaquelocktoken:{lock_obj.token}>"},
    )

    response = await dav_provider.do_unlock(request)

    assert response.status == 400


@pytest.mark.asyncio
async def test_do_mkcol_dispatches_to_provider(
    dav_provider: DAVProvider,
) -> None:
    # the base class dispatches MKCOL to the provider implementation; the
    # base class itself does not implement it
    request = create_dav_request_object(method="MKCOL", path=RES_PATH_1.raw)
    request.lock_ifs = []

    with pytest.raises(NotImplementedError):
        await dav_provider.do_mkcol(request)


@pytest.mark.asyncio
async def test_do_mkcol_with_body_415(dav_provider: DAVProvider) -> None:
    # RFC 4918: MKCOL with a request body MUST fail with 415
    request = create_dav_request_object(method="MKCOL", path=RES_PATH_1.raw)
    request.lock_ifs = []

    async def receive() -> ASGIReceiveEvent:
        return {"type": "http.request", "body": b"unexpected body", "more_body": False}

    request.receive = receive

    response = await dav_provider.do_mkcol(request)

    assert response.status == 415
