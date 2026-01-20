from __future__ import annotations

import pprint
import re
import urllib.parse
from dataclasses import dataclass, field
from functools import cached_property
from logging import getLogger
from urllib.parse import urlparse
from uuid import UUID

from asgiref.typing import ASGIReceiveCallable, ASGISendCallable, HTTPScope

from asgi_webdav.constants import (
    DAV_PROPERTY_BASIC_KEYS,
    DAVDepth,
    DAVHeaders,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
    DAVMethod,
    DAVPath,
    DAVPropertyIdentity,
    DAVPropertyPatchEntry,
    DAVRangeType,
    DAVRequestBodyLock,
    DAVRequestIf,
    DAVRequestIfCondition,
    DAVRequestIfConditionType,
    DAVRequestRange,
    DAVUser,
)
from asgi_webdav.exceptions import DAVCodingError, DAVRequestParseError
from asgi_webdav.helpers import get_dict_from_xml, is_etag, receive_all_data_in_one_call

logger = getLogger(__name__)


_XML_NAME_SPACE_TAG = "@xmlns"


# https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Reference/Headers/If-Range
# If-Range: <day-name>, <day> <month> <year> <hour>:<minute>:<second> GMT
# If-Range: <etag>
# If-Range: Wed, 21 Oct 2015 07:28:00 GMT
# If-Range: "67ab43"
# If-Range: W/"67ab43"
@dataclass(slots=True)
class DAVRequestIfRange:
    raw: bytes

    etag: str = field(init=False)
    last_modified: str = field(init=False)

    def __post_init__(self) -> None:
        data = self.raw.decode()
        if is_etag(data):
            self.etag = data
            self.last_modified = ""
        else:
            # TODO: end with GMT?
            self.etag = ""
            self.last_modified = data

    def match(self, etag: str, last_modified: str) -> bool:
        if self.etag:
            return self.etag == etag
        else:
            return self.last_modified == last_modified


# https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Reference/Headers/Range
# Range: <unit>=<range-start>-
# Range: <unit>=<range-start>-<range-end>
# Range: <unit>=<range-start>-<range-end>, …, <range-startN>-<range-endN>
# Range: <unit>=-<suffix-length>
def _parse_header_range(header_range: bytes | None) -> list[DAVRequestRange]:
    if header_range is None:
        return []

    header_range_str = header_range.decode("utf-8").lower()
    if header_range_str[:6] != "bytes=":
        # TODO: exception
        return []

    result = list()
    for content_range in header_range_str[6:].split(","):
        range_data = content_range.strip(" ").split("-")

        try:
            if range_data[0]:
                start = int(range_data[0])
            else:
                start = None

        except (ValueError, IndexError):
            # TODO: exception
            start = None

        try:
            if range_data[1]:
                end = int(range_data[1])
            else:
                end = None

        except (ValueError, IndexError):
            # TODO: exception
            end = None

        match start, end:
            case int(), int():
                if start < 0 or start >= end:
                    # TODO: exception
                    continue

                result.append(
                    DAVRequestRange(
                        type=DAVRangeType.RANGE,
                        range_start=start,
                        range_end=end,
                    )
                )
            case int(), None:
                result.append(
                    DAVRequestRange(type=DAVRangeType.RANGE, range_start=start)
                )
            case None, int():
                if end == 0:
                    # TODO: exception
                    continue

                result.append(
                    DAVRequestRange(type=DAVRangeType.SUFFIX, suffix_length=end)
                )
            case None, None:
                # TODO: exception
                pass

    if len(result) >= 2:
        for i in range(len(result)):
            if result[i].type == DAVRangeType.SUFFIX:
                # TODO: exception
                return []

    return result


# - https://datatracker.ietf.org/doc/html/rfc4918#section-10.5
# 10.5.  Lock-Token Header
#       Lock-Token = "Lock-Token" ":" Coded-URL
#
#    The Lock-Token request header is used with the UNLOCK method to
#    identify the lock to be removed.  The lock token in the Lock-Token
#    request header MUST identify a lock that contains the resource
#    identified by Request-URI as a member.
#
#    The Lock-Token response header is used with the LOCK method to
#    indicate the lock token created as a result of a successful LOCK
#    request to create a new lock.
#
# UNLOCK /container/file.txt HTTP/1.1
# Host: example.com
# Lock-Token: <opaquelocktoken:f81d4fae-7dec-11d0-a765-00a0c91e6bf6>
def _parse_header_lock_token(header_lock_token: bytes | None) -> UUID | None:
    if header_lock_token is None:
        return None

    pattern = rb"<opaquelocktoken:([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})>"
    match = re.search(pattern, header_lock_token, re.IGNORECASE)

    if match is None:
        return None

    token = UUID(match.group(1).decode())
    if token.version == 4:
        return token

    return None


# - https://datatracker.ietf.org/doc/html/rfc4918#section-10.4
# 10.4.  If Header
#
#    The If request header is intended to have similar functionality to
#    the If-Match header defined in Section 14.24 of [RFC2616].  However,
#    the If header handles any state token as well as ETags.  A typical
#    example of a state token is a lock token, and lock tokens are the
#    only state tokens defined in this specification.
class DAVRequestIfParser:
    # 1. 顶层正则：匹配 <资源URI> 或者 (条件列表)
    # group 'resource': 匹配 <...> 外部的资源标签
    # group 'list': 匹配 (...) 内部的条件列表
    _OUTER_PATTERN = re.compile(r"(?:<(?P<resource>[^>]+)>)|(?P<list>\s*\((?:[^)]+)\))")

    # 2. 内部正则：匹配 List 内部的 Not, <Token>, [ETag]
    # group 'not': 匹配 Not 关键字
    # group 'no_lock': 匹配 <DAV:no-lock>
    # group 'token': 匹配 <...> 形式的 State Token
    # group 'etag': 匹配 [...] 形式的 ETag
    _INNER_PATTERN = re.compile(
        r"(?P<not>Not)|(?P<no_lock><DAV:no-lock>)|<(opaquelocktoken:|urn:uuid:)(?P<token>[^>]+)>|\[(?P<etag>[^\]]*)\]",
        re.IGNORECASE,
    )

    @classmethod
    def parse(cls, header_if: str, default_res_path: DAVPath) -> list[DAVRequestIf]:
        """
        解析 If 头字符串。

        返回结构:
        {
            '资源URI (None 表示 No-tag-list)': [
                [Condition1, Condition2],  # OR 逻辑中的第一个列表 (AND 关系)
                [Condition3]               # OR 逻辑中的第二个列表
            ]
        }
        """
        current_res_path = default_res_path

        request_ifs: list[DAVRequestIf] = list()
        data: dict[DAVPath, list[list[DAVRequestIfCondition]]] = dict()
        # 扫描顶层结构
        for match in cls._OUTER_PATTERN.finditer(header_if):
            if match.group("resource"):
                # 发现资源标签，更新当前上下文
                res_url_data = urlparse(match.group("resource"))
                current_res_path = DAVPath(res_url_data.path)

            elif match.group("list"):
                # 发现条件列表 (...)
                list_content = match.group("list")
                parsed_conditions = cls._parse_inner_list(list_content)
                if len(parsed_conditions) == 0:
                    # TODO: parse failed, maybe raise?
                    continue

                if current_res_path not in data:
                    data[current_res_path] = list()

                data[current_res_path].append(parsed_conditions)

        for k, v in data.items():
            request_ifs.append(DAVRequestIf(res_path=k, conditions=v))

        return request_ifs

    @classmethod
    def _parse_inner_list(cls, list_str: str) -> list[DAVRequestIfCondition]:
        """解析括号内部的条件，例如: (Not <urn:x> [etag])"""
        conditions: list[DAVRequestIfCondition] = []

        is_not = False
        for match in cls._INNER_PATTERN.finditer(list_str):
            if match.group("not"):
                is_not = True
                continue

            if match.group("token"):
                conditions.append(
                    DAVRequestIfCondition(
                        is_not=is_not,
                        type=DAVRequestIfConditionType.TOKEN,
                        data=match.group("token"),
                    )
                )
                is_not = False

            elif match.group("no_lock"):
                conditions.append(
                    DAVRequestIfCondition(
                        is_not=is_not, type=DAVRequestIfConditionType.NO_LOCK, data=""
                    )
                )
                is_not = False

            elif match.group("etag"):
                conditions.append(
                    DAVRequestIfCondition(
                        is_not=is_not,
                        type=DAVRequestIfConditionType.ETAG,
                        data=match.group("etag"),
                    )
                )
                is_not = False

        return conditions


def _parse_header_ifs(
    header_if: bytes | None, default_res_path: DAVPath
) -> list[DAVRequestIf]:
    if header_if is None:
        return []

    return DAVRequestIfParser.parse(header_if.decode(), default_res_path)


# - https://datatracker.ietf.org/doc/html/rfc4918#page-78
# 10.7.  Timeout Request Header
#
#       TimeOut = "Timeout" ":" 1#TimeType
#       TimeType = ("Second-" DAVTimeOutVal | "Infinite")
#                  ; No LWS allowed within TimeType
#       DAVTimeOutVal = 1*DIGIT
#
#    Clients MAY include Timeout request headers in their LOCK requests.
#    However, the server is not required to honor or even consider these
#    requests.  Clients MUST NOT submit a Timeout request header with any
#    method other than a LOCK method.
#
#    The "Second" TimeType specifies the number of seconds that will
#    elapse between granting of the lock at the server, and the automatic
#    removal of the lock.  The timeout value for TimeType "Second" MUST
#    NOT be greater than 2^32-1.
#
#    See Section 6.6 for a description of lock timeout behavior.
def _parse_header_timeout(header_timeout: bytes | None) -> int:
    """return 0: timeout parse failed"""
    if header_timeout is None:
        return 0

    timeout_str = header_timeout[7:].decode()
    if timeout_str == "Infinite":
        return DAVLockTimeoutMaxValue

    try:
        timeout = int(timeout_str)
    except ValueError:
        return 0

    return timeout


# - https://datatracker.ietf.org/doc/html/rfc4918#section-10.2
# 10.2.  Depth Header
#
#       Depth = "Depth" ":" ("0" | "1" | "infinity")
#
#    The Depth request header is used with methods executed on resources
#    that could potentially have internal members to indicate whether the
#    method is to be applied only to the resource ("Depth: 0"), to the
#    resource and its internal members only ("Depth: 1"), or the resource
#    and all its members ("Depth: infinity").
def _parse_header_depth(header_depth: bytes | None) -> DAVDepth:
    match header_depth:
        case b"0" | None:
            # default' value
            return DAVDepth.ZERO

        case b"1":
            return DAVDepth.ONE

        case b"infinity":
            return DAVDepth.INFINITY

        case _:
            raise DAVRequestParseError(f"bad depth:{header_depth.decode()}")


# - https://datatracker.ietf.org/doc/html/rfc4918#page-77
# 10.6.  Overwrite Header
#
#       Overwrite = "Overwrite" ":" ("T" | "F")
#
#    The Overwrite request header specifies whether the server should
#    overwrite a resource mapped to the destination URL during a COPY or
#    MOVE.  A value of "F" states that the server must not perform the
#    COPY or MOVE operation if the destination URL does map to a resource.
#    If the overwrite header is not included in a COPY or MOVE request,
#    then the resource MUST treat the request as if it has an overwrite
#    header of value "T".  While the Overwrite header appears to duplicate
#    the functionality of using an "If-Match: *" header (see [RFC2616]),
#    If-Match applies only to the Request-URI, and not to the Destination
#    of a COPY or MOVE.
#
#    If a COPY or MOVE is not performed due to the value of the Overwrite
#    header, the method MUST fail with a 412 (Precondition Failed) status
#    code.  The server MUST do authorization checks before checking this
#    or any conditional header.
#
#    All DAV-compliant resources MUST support the Overwrite header.
# overwrite
def _parse_header_overwrite(header_overwrite: bytes | None) -> bool:
    match header_overwrite:
        case b"T" | None:
            # default' value
            return True

        case b"F":
            return False

        case _:
            raise DAVRequestParseError(
                f"bad header_overwrite:{header_overwrite.decode()}"
            )


# - https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Accept-Encoding
# The HTTP Accept-Encoding request and response header indicates the content encoding (usually a compression algorithm) that the sender can understand. In requests, the server uses content negotiation to select one of the encoding proposals from the client and informs the client of that choice with the Content-Encoding response header. In responses, it provides information about which content encodings the server can understand in messages to the requested resource, so that the encoding can be used in subsequent requests to the resource. For example, Accept-Encoding is included in a 415 Unsupported Media Type response if a request to a resource (e.g., PUT) used an unsupported encoding.
#
# Accept-Encoding: gzip
# Accept-Encoding: compress
# Accept-Encoding: deflate
# Accept-Encoding: br
# Accept-Encoding: zstd
# Accept-Encoding: dcb
# Accept-Encoding: dcz
# Accept-Encoding: identity
# Accept-Encoding: *
#
# // Multiple algorithms, weighted with the quality value syntax:
# Accept-Encoding: deflate, gzip;q=1.0, *;q=0.5
def _parse_header_accept_encoding(header_accept_encoding: bytes | None) -> str:
    match header_accept_encoding:
        case None:
            # default' value
            return ""

        case _:
            return header_accept_encoding.decode()


@dataclass
class DAVRequest:
    """Information from Request
    DAVDistributor => DavProvider => provider.implement
    """

    # init data
    scope: HTTPScope
    receive: ASGIReceiveCallable
    send: ASGISendCallable

    # client info
    client_ip_address: str = field(init=False)
    client_user_agent: str = field(init=False)

    # basic's info ---
    method: DAVMethod = field(init=False)
    headers: DAVHeaders = field(init=False)
    # body's info ---
    body: bytes = field(init=False)
    body_is_parsed_success: bool = False

    # path's info ---
    src_path: DAVPath = field(init=False)
    dst_path: DAVPath | None = None
    query_string: str = field(init=False)

    # fragment, ASGI server doesn't forward fragment info to application
    @property
    def path(self) -> DAVPath:
        return self.src_path

    @cached_property
    def depth(self) -> DAVDepth:
        return _parse_header_depth(self.headers.get(b"depth"))

    @cached_property
    def overwrite(self) -> bool:
        return _parse_header_overwrite(self.headers.get(b"overwrite"))

    # Range Info ---
    @cached_property
    def ranges(self) -> list[DAVRequestRange]:
        if self.method != DAVMethod.GET:
            raise DAVCodingError()  # pragma: no cover

        return _parse_header_range(self.headers.get(b"range"))

    @cached_property
    def if_range(self) -> DAVRequestIfRange | None:
        data = self.headers.get(b"if-range")
        if data is None:
            return None

        return DAVRequestIfRange(data)

    # propfind info ---
    propfind_only_fetch_property_name: bool = False  # TODO!!!

    propfind_fetch_all_property: bool = True
    propfind_only_fetch_basic: bool = False
    propfind_basic_keys: set[str] = field(default_factory=set)
    propfind_extra_keys: list[DAVPropertyIdentity] = field(default_factory=list)

    # proppatch info ---
    proppatch_entries: list[DAVPropertyPatchEntry] = field(default_factory=list)

    # lock info --- (in both header and body)
    @cached_property
    def lock_ifs(self) -> list[DAVRequestIf]:
        """header: if"""
        # TODO: In practice there will be no cases where there is more than one DAVRequestIf, so maybe we can remove some code for performance?
        return _parse_header_ifs(self.headers.get(b"if"), self.src_path)

    @cached_property
    def lock_token(self) -> UUID | None:
        """header: lock-token
        - only for method UNLOCK in request header"""
        # TODO: py3.14+ uuid.NIL
        return _parse_header_lock_token(self.headers.get(b"lock-token"))

    @cached_property
    def timeout(self) -> int:
        """header: timeout
        - only for method LOCK"""
        return _parse_header_timeout(self.headers.get(b"timeout"))

    # --- lock info in body; only for method LOCK
    body_lock: DAVRequestBodyLock | None = None

    # distribute information
    dist_prefix: DAVPath = field(init=False)
    dist_src_path: DAVPath = field(init=False)
    dist_dst_path: DAVPath = field(init=False)

    # session info - update in DAVAuth.pick_out_user()
    user: DAVUser = field(init=False)
    authorization_info: bytes = b""
    authorization_method: str = ""

    # response relate
    @cached_property
    def accept_encoding(self) -> str:
        return _parse_header_accept_encoding(self.headers.get(b"accept-encoding"))

    def __post_init__(self) -> None:
        self.method = DAVMethod(self.scope.get("method", "UNKNOWN"))
        self.headers = DAVHeaders(self.scope.get("headers", []))
        user_agent = self.headers.get(b"user-agent")
        if user_agent is None:
            self.client_user_agent = ""
        else:
            self.client_user_agent = user_agent.decode("utf-8")

        self._parser_client_ip_address()

        # path
        raw_path = self.scope.get("path", "")
        self.src_path = DAVPath(urllib.parse.unquote(raw_path, encoding="utf-8"))
        raw_url = self.headers.get(b"destination")
        if raw_url:
            self.dst_path = DAVPath(
                urllib.parse.unquote(
                    urllib.parse.urlparse(raw_url.decode("utf-8")).path
                )
            )

        # TODO: remove it?
        self.query_string = self.scope.get("query_string", b"").decode("utf-8")
        return

    def _parser_client_ip_address(self) -> None:
        ip_address = self.headers.get(b"x-real-ip")
        if ip_address is not None:
            self.client_ip_address = ip_address.decode("utf-8")
            return

        ip_address = self.headers.get(b"x-forwarded-for")
        if ip_address is not None:
            self.client_ip_address = ip_address.decode("utf-8").split(",")[0]
            return

        ip_address_client = self.scope.get("client")
        if ip_address_client is None:
            self.client_ip_address = ""
        else:
            self.client_ip_address = ip_address_client[0]

        return

    def update_distribute_info(self, dist_prefix: DAVPath) -> None:
        self.dist_prefix = dist_prefix
        self.dist_src_path = self.src_path.get_child(dist_prefix)
        if self.dst_path:
            self.dist_dst_path = self.dst_path.get_child(dist_prefix)

    @staticmethod
    def _cut_ns_key(ns_key: str) -> tuple[str, str]:
        index = ns_key.rfind(":")
        if index == -1:
            return "", ns_key
        else:
            return ns_key[:index], ns_key[index + 1 :]

    async def _parser_body_propfind(self) -> bool:
        """
        A client may choose not to submit a request body.  An empty PROPFIND
           request body MUST be treated as if it were an 'allprop' request.
        """
        if len(self.body) == 0:
            # allprop
            return True

        data = get_dict_from_xml(self.body, "propfind")
        if not data:
            return False

        if "propname" in data:
            self.propfind_only_fetch_property_name = True
            return True

        if "DAV::allprop" in data:
            return True
        else:
            self.propfind_fetch_all_property = False

        if "DAV::prop" not in data:
            # TODO error
            return False

        for ns_key in data["DAV::prop"]:
            if not isinstance(ns_key, str):
                # app filebar: {'@xmlns': {'D': 'DAV:'}, 'DAV::prop': [{'DAV::quota-used-bytes': None}, {'DAV::quota-available-bytes': None}, {'DAV::resourcetype': None}]}
                # TODO: 临时解决方案,直接丢弃.后续需要参考 proppatch 方法的处理
                continue

            ns, key = self._cut_ns_key(ns_key)
            if key in DAV_PROPERTY_BASIC_KEYS:
                self.propfind_basic_keys.add(key)
            else:
                self.propfind_extra_keys.append((ns, key))

        if len(self.propfind_extra_keys) == 0:
            self.propfind_only_fetch_basic = True

        return True

    async def _parser_body_proppatch(self) -> bool:
        data = get_dict_from_xml(self.body, "propertyupdate")
        if not data:
            return False

        for action, action_data in data.items():
            if action == _XML_NAME_SPACE_TAG:
                continue

            _, action_method = self._cut_ns_key(action)
            if action_method == "set":
                method = True
            else:
                # remove
                method = False

            if isinstance(action_data, dict):
                # 当 action 只有一条的时候, actions_data 是一个 dict, 需要转换为 list 以便后续处理
                action_data = [action_data]

            for action_item in action_data:

                ns_key, dav_prop_data = action_item["DAV::prop"].popitem()
                ns, key = self._cut_ns_key(ns_key)

                # value = value.get("#text")
                value = None
                for prop_key, prop_value in dav_prop_data.items():
                    if prop_key == _XML_NAME_SPACE_TAG:
                        continue
                    if prop_key == "#text":
                        value = prop_value
                    else:
                        _, value = self._cut_ns_key(prop_key)

                if not isinstance(value, str):
                    value = str(value)  # TODO: 可能不需要转换?

                self.proppatch_entries.append(((ns, key), value, method))

        return True

    async def _parser_body_lock(self) -> bool:
        if len(self.body) == 0:
            # LOCK accept empty body
            return True

        data = get_dict_from_xml(self.body, "lockinfo")
        if not data:
            return False

        try:
            if "DAV::exclusive" in data["DAV::lockscope"]:
                lock_scope = DAVLockScope.EXCLUSIVE
            else:
                lock_scope = DAVLockScope.SHARED

            lock_owner = data["DAV::owner"]

        except KeyError:
            return False

        self.body_lock = DAVRequestBodyLock(
            scope=lock_scope,
            owner=str(lock_owner),
        )
        return True

    async def parser_body(self) -> bool:
        match self.method:
            case DAVMethod.PROPFIND:
                self.body = await receive_all_data_in_one_call(self.receive)
                self.body_is_parsed_success = await self._parser_body_propfind()

            case DAVMethod.PROPPATCH:
                self.body = await receive_all_data_in_one_call(self.receive)
                self.body_is_parsed_success = await self._parser_body_proppatch()

            case DAVMethod.LOCK:
                self.body = await receive_all_data_in_one_call(self.receive)
                self.body_is_parsed_success = await self._parser_body_lock()

            case _:
                self.body_is_parsed_success = False

        return self.body_is_parsed_success

    def change_from_get_to_propfind_d1_for_dir_browser(self) -> None:
        if self.method != DAVMethod.GET:
            raise  # TODO

        self.method = DAVMethod.PROPFIND
        self.depth = DAVDepth.ONE

    def __repr__(self) -> str:
        simple_fields = ["method", "src_path", "accept_encoding"]
        rich_fields = list()

        match self.method:
            case DAVMethod.PROPFIND:
                simple_fields += [
                    "depth",
                    "body_is_parsed_success",
                    "propfind_only_fetch_property_name",
                    "propfind_fetch_all_property",
                    "propfind_only_fetch_basic",
                    "propfind_basic_keys",
                ]
                rich_fields += [
                    "propfind_extra_keys",
                ]

            case DAVMethod.PROPPATCH:
                simple_fields += ["depth", "body_is_parsed_success"]
                rich_fields += ["lock_ifs", "proppatch_entries"]

            case DAVMethod.GET:
                rich_fields += ["ranges", "if_range"]

            case DAVMethod.PUT:
                rich_fields += ["lock_ifs"]

            case DAVMethod.COPY | DAVMethod.MOVE:
                simple_fields += ["dst_path", "depth", "overwrite"]
                rich_fields += ["lock_ifs"]

            case DAVMethod.LOCK:
                simple_fields += [
                    "depth",
                    "timeout",
                    "body_is_parsed_success",
                    "body_lock",
                ]
                rich_fields += ["lock_ifs"]

            case DAVMethod.UNLOCK:
                simple_fields += ["lock_token"]

            case _:
                pass

        simple = "|".join([str(self.__getattribute__(name)) for name in simple_fields])

        try:
            username = self.user.username
        except AttributeError:
            username = None

        scope = pprint.pformat(self.scope)
        rich = "\n".join(
            [pprint.pformat(self.__getattribute__(name)) for name in rich_fields]
        )
        s = f"{username}|{simple}\n{scope}\n{rich}"

        return s
