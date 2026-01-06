from uuid import UUID

import pytest
from icecream import ic

from asgi_webdav.constants import (
    DAVLockTimeoutMaxValue,
    DAVPath,
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
    HEADER_IF_ETAG_1,
    HEADER_IF_ETAG_2,
    HEADER_IF_UUID_1,
    HEADER_IF_UUID_2,
    LOCK_UUID_1,
    LOCK_UUID_2,
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
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}])".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}>)".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            )
                        ],
                    ],
                )
            ],
        ),
        (
            # uuid, etag
            f"(<{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}])".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # uuid
            f"(<{HEADER_IF_UUID_1}>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            )
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid2, uuid1, etag
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_2}> <{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}])".encode(),
            RES_URL_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, NOT uuid2, uuid1, etag
            f"<{RES_URL_1}> (Not <{HEADER_IF_UUID_2}> <{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}])".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                True, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            # res, uuid1, etag | uuid2
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}]) (<{HEADER_IF_UUID_2}>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    conditions=[
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            ),
                        ],
                    ],
                ),
            ],
        ),
        (
            # res, uuid, etag; res2, uuid2, etag
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}]) <{RES_URL_2}> (<{HEADER_IF_UUID_2}> [{HEADER_IF_ETAG_2}])".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                ),
                DAVRequestIf(
                    RES_PATH_2,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_2
                            ),
                        ],
                    ],
                ),
            ],
        ),
        (
            # res, uuid1; res uuid2
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}>) <{RES_URL_2}> (<{HEADER_IF_UUID_2}>)".encode(),
            None,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            )
                        ],
                    ],
                ),
                DAVRequestIf(
                    RES_PATH_2,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            )
                        ],
                    ],
                ),
            ],
        ),
        (
            # uuid1; uuid2
            f"(<{HEADER_IF_UUID_1}>) (<{HEADER_IF_UUID_2}>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                        ],
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_2
                            )
                        ],
                    ],
                ),
            ],
        ),
        (
            # Not <DAV:no-lock>
            f"(<{HEADER_IF_UUID_1}>) (Not <DAV:no-lock>)".encode(),
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                        ],
                        [
                            DAVRequestIfCondition(
                                True, DAVRequestIfConditionType.NO_LOCK, ""
                            ),
                        ],
                    ],
                )
            ],
        ),
    ],
)
def test_parse_header_if(header_if, default_res_path, expected_output):
    request_if = _parse_header_ifs(header_if, default_res_path)
    ic(request_if)
    ic(expected_output)
    assert request_if == expected_output


@pytest.mark.parametrize(
    "header_if, default_res_path, expected",
    [
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.6
        # 10.4.6.  Example - No-tag Production
        (
            b'(<urn:uuid:181d4fae-7d8c-11d0-a765-00a0c91e6bf2> ["I am an ETag"]) (["I am another ETag"])',
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                "181d4fae-7d8c-11d0-a765-00a0c91e6bf2",
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
            ],
        ),
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.7
        # 10.4.7.  Example - Using "Not" with No-tag Production
        (
            b"(Not <urn:uuid:181d4fae-7d8c-11d0-a765-00a0c91e6bf2> <urn:uuid:58f202ac-22cf-11d1-b12d-002035b29092>)",
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                True,
                                DAVRequestIfConditionType.TOKEN,
                                "181d4fae-7d8c-11d0-a765-00a0c91e6bf2",
                            ),
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                "58f202ac-22cf-11d1-b12d-002035b29092",
                            ),
                        ],
                    ],
                )
            ],
        ),
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.8
        # 10.4.8.  Example - Causing a Condition to Always Evaluate to True
        (
            b"(<urn:uuid:181d4fae-7d8c-11d0-a765-00a0c91e6bf2>) (Not <DAV:no-lock>)",
            RES_PATH_1,
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                "181d4fae-7d8c-11d0-a765-00a0c91e6bf2",
                            ),
                        ],
                        [
                            DAVRequestIfCondition(
                                True, DAVRequestIfConditionType.NO_LOCK, ""
                            ),
                        ],
                    ],
                )
            ],
        ),
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.9
        # 10.4.9.  Example - Tagged List If Header in COPY
        (
            b'</resource1> (<urn:uuid:181d4fae-7d8c-11d0-a765-00a0c91e6bf2> [W/"A weak ETag"]) (["strong ETag"])',
            DAVPath("/resource1"),
            [
                DAVRequestIf(
                    DAVPath("/resource1"),
                    [
                        [
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                "181d4fae-7d8c-11d0-a765-00a0c91e6bf2",
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
            ],
        ),
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.10
        # 10.4.10.  Example - Matching Lock Tokens with Collection Locks
        (
            b"<http://www.example.com/specs/> (<urn:uuid:181d4fae-7d8c-11d0-a765-00a0c91e6bf2>)",
            None,
            [
                DAVRequestIf(
                    DAVPath("/specs"),
                    [
                        [
                            DAVRequestIfCondition(
                                False,
                                DAVRequestIfConditionType.TOKEN,
                                "181d4fae-7d8c-11d0-a765-00a0c91e6bf2",
                            ),
                        ],
                    ],
                )
            ],
        ),
        # - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4.11
        # 10.4.11.  Example - Matching ETags on Unmapped URLs
        (
            b'</specs/rfc2518.doc> (["4217"])',
            None,
            [
                DAVRequestIf(
                    DAVPath("/specs/rfc2518.doc"),
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, '"4217"'
                            ),
                        ],
                    ],
                )
            ],
        ),
        (
            b'</specs/rfc2518.doc> (Not ["4217"])',
            None,
            [
                DAVRequestIf(
                    DAVPath("/specs/rfc2518.doc"),
                    [
                        [
                            DAVRequestIfCondition(
                                True, DAVRequestIfConditionType.ETAG, '"4217"'
                            ),
                        ],
                    ],
                )
            ],
        ),
    ],
)
def test_parse_header_if_rfc4918_examples(header_if, default_res_path, expected):
    request_if = _parse_header_ifs(header_if, default_res_path)
    ic(request_if)
    ic(expected)
    assert request_if == expected


@pytest.mark.parametrize(
    "header_if, default_res_path, expected_output",
    [
        (
            # res, uuid, etag
            f"<{RES_URL_1}> (<{HEADER_IF_UUID_1}> [{HEADER_IF_ETAG_1}])".encode(),
            RES_URL_2,  # wrong default_res_path
            [
                DAVRequestIf(
                    RES_PATH_1,
                    [
                        [
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.TOKEN, LOCK_UUID_1
                            ),
                            DAVRequestIfCondition(
                                False, DAVRequestIfConditionType.ETAG, HEADER_IF_ETAG_1
                            ),
                        ],
                    ],
                )
            ],
        ),
        (None, None, []),  # header_if is None
    ],
)  # TODO: more test!!!!
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
