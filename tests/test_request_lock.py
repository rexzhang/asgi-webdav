from uuid import UUID

import pytest
from icecream import ic

from asgi_webdav.constants import (
    DAVLockTimeoutMaxValue,
    DAVRequestIf,
    DAVRequestIfCondition,
    DAVRequestIfConditionType,
)
from asgi_webdav.request import (
    _parse_header_ifs,
    _parse_header_lock_token,
    _parse_header_timeout,
)
from tests.kits.lock import (
    HEADER_IF_ETAG1,
    HEADER_IF_ETAG2,
    HEADER_IF_UUID1,
    HEADER_IF_UUID2,
    RES_PATH_1,
    RES_PATH_2,
    RES_URL_1,
    RES_URL_2,
)

# 模拟测试数据
HEADER_LOCK_TOKEN_UUID = UUID("5fba2973-ae54-4b38-bbf5-e21c2f727190")


@pytest.mark.parametrize(
    "input_data, expected_output",
    [
        # 标准正确格式
        (
            b"<opaquelocktoken:5fba2973-ae54-4b38-bbf5-e21c2f727190>",
            HEADER_LOCK_TOKEN_UUID,
        ),
        # 大写前缀和 UUID
        (
            b"<OPAQUELOCKTOKEN:5FBA2973-AE54-4B38-BBF5-E21C2F727190>",
            HEADER_LOCK_TOKEN_UUID,
        ),
        # 包含在更长的二进制流中
        (
            b"prefix_data\x00<opaquelocktoken:5fba2973-ae54-4b38-bbf5-e21c2f727190>\xff",
            HEADER_LOCK_TOKEN_UUID,
        ),
        # 缺少前缀（应失败）
        (b"<otherprefix:5fba2973-ae54-4b38-bbf5-e21c2f727190>", None),
        # 格式不完整：缺少尖括号（应失败）
        (b"opaquelocktoken:5fba2973-ae54-4b38-bbf5-e21c2f727190", None),
        # UUID 长度不对（应失败）
        (b"<opaquelocktoken:5fba2973-ae54-4b38-bbf5-e21c2f72719>", None),
        # 错误的 UUID
        (b"<opaquelocktoken:5fba2973-ae54-0b38-bbf5-e21c2f727190>", None),
        (b"<opaquelocktoken:5fba2973-ae54-4b38-7bf5-e021c2f727190>", None),
        # 没有 uuid 部分
        (b"<opaquelocktoken:>", None),
        # 空数据
        (b"", None),
        (None, None),
    ],
)
def test_parse_header_lock_token(input_data, expected_output):
    assert _parse_header_lock_token(input_data) == expected_output


@pytest.mark.parametrize(
    "header_if, default_res_path, expected_output",
    [
        (
            # res, uuid, etag
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}])".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID1)}>)".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            )
                        ],
                    ],
                )
            ],
        ),
        (
            # uuid, etag
            f"(<{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}])".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # uuid
            f"(<{str(HEADER_IF_UUID1)}>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            )
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid2, uuid1, etag
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID2)}> <{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}])".encode(),
            RES_URL_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, NOT uuid2, uuid1, etag
            f"<{RES_URL_1}> (Not <{str(HEADER_IF_UUID2)}> <{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}])".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                True, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid1, etag | uuid2
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}]) (<{str(HEADER_IF_UUID2)}>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    conditions=[
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID2
                            ),
                        ],
                    ],
                ),
            ],
        ),
        (
            # res, uuid, etag; res2, uuid2, etag
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}]) <{RES_URL_2}> (<{str(HEADER_IF_UUID2)}> [{HEADER_IF_ETAG2}])".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                ),
                DAVRequestIf(
                    RES_PATH_2,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG2
                            ),
                        ],
                    ],
                ),
            ],
        ),
    ],
)
def test__parse_header_if(header_if, default_res_path, expected_output):
    request_if = _parse_header_ifs(header_if, default_res_path)
    ic(request_if)
    ic(expected_output)
    assert request_if == expected_output


@pytest.mark.parametrize(
    "header_if, default_res_path, expected_output",
    [
        (
            # res, uuid, etag
            f"<{RES_URL_1}> (<{str(HEADER_IF_UUID1)}> [{HEADER_IF_ETAG1}])".encode(),
            RES_URL_2,  # wrong default_res_path
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, HEADER_IF_UUID1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (None, None, []),  # header_if is None
    ],
)
def test_parse_header_if_some_thing_wrong(header_if, default_res_path, expected_output):
    request_if = _parse_header_ifs(header_if, default_res_path)
    ic(request_if)
    ic(expected_output)
    assert request_if == expected_output


def test_parse_header_timeout():
    assert _parse_header_timeout(b"Second-1000") == 1000
    assert _parse_header_timeout(b"Second-Infinite") == DAVLockTimeoutMaxValue

    # empty
    assert _parse_header_timeout(None) == 0

    # invalid
    assert _parse_header_timeout(b"Second-") == 0
    assert _parse_header_timeout(b"Second-invalid") == 0
    assert _parse_header_timeout(b"invalid") == 0
    assert _parse_header_timeout(b"a") == 0
