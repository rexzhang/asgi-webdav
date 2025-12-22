import pprint
import urllib.parse
from dataclasses import dataclass, field
from logging import getLogger
from pyexpat import ExpatError
from uuid import UUID

from asgiref.typing import ASGIReceiveCallable, ASGISendCallable, HTTPScope

from asgi_webdav.constants import (
    DAV_PROPERTY_BASIC_KEYS,
    DAVDepth,
    DAVHeaders,
    DAVLockScope,
    DAVMethod,
    DAVPath,
    DAVPropertyIdentity,
    DAVPropertyPatchEntry,
    DAVUser,
)
from asgi_webdav.helpers import (
    get_dict_from_xml,
    receive_all_data_in_one_call,
)

logger = getLogger(__name__)


_XML_NAME_SPACE_TAG = "@xmlns"


@dataclass(slots=True)
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

    # header's info ---
    method: DAVMethod = field(init=False)
    headers: DAVHeaders = field(init=False)
    src_path: DAVPath = field(init=False)
    dst_path: DAVPath | None = None
    query_string: str = field(init=False)
    # fragment, ASGI server doesn't forward fragment info to application
    depth: DAVDepth = DAVDepth.d0
    overwrite: bool = field(init=False)
    timeout: int = field(init=False)

    @property
    def path(self) -> DAVPath:
        return self.src_path

    # Range
    # only response first range
    content_range: bool = False
    content_range_start: int | None = None
    content_range_end: int | None = None

    # body's info ---
    body: bytes = field(init=False)
    body_is_parsed_success: bool = False

    # propfind info ---
    propfind_only_fetch_property_name: bool = False  # TODO!!!

    propfind_fetch_all_property: bool = True
    propfind_only_fetch_basic: bool = False
    propfind_basic_keys: set[str] = field(default_factory=set)
    propfind_extra_keys: list[DAVPropertyIdentity] = field(default_factory=list)

    # proppatch info ---
    proppatch_entries: list[DAVPropertyPatchEntry] = field(default_factory=list)

    # lock info --- (in both header and body)
    lock_scope: DAVLockScope | None = None
    lock_owner: str | None = None
    lock_token: UUID | None = None
    lock_token_path: DAVPath | None = None  # from header.If
    lock_token_etag: str | None = None
    lock_token_is_parsed_success: bool = True

    # distribute information
    dist_prefix: DAVPath = field(init=False)
    dist_src_path: DAVPath = field(init=False)
    dist_dst_path: DAVPath = field(init=False)

    # session info - update in DAVAuth.pick_out_user()
    user: DAVUser = field(init=False)
    authorization_info: bytes = b""
    authorization_method: str = ""

    # response info
    accept_encoding: str = ""

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

        self.query_string = self.scope.get("query_string", b"").decode("utf-8")

        # depth
        """
        https://www.rfc-editor.org/rfc/rfc4918#section-10.2
        10.2.  Depth Header

            Depth = "Depth" ":" ("0" | "1" | "infinity")

        The Depth request header is used with methods executed on resources
        that could potentially have internal members to indicate whether the
        method is to be applied only to the resource ("Depth: 0"), to the
        resource and its internal members only ("Depth: 1"), or the resource
        and all its members ("Depth: infinity").
        """
        depth = self.headers.get(b"depth")
        if depth is None:
            # default' value
            pass

        elif depth == b"infinity":
            self.depth = DAVDepth.infinity

        else:
            try:
                match int(depth):
                    case 0:
                        self.depth = DAVDepth.d0
                    case 1:
                        self.depth = DAVDepth.d1
                    case _:
                        raise ValueError

            except ValueError:
                raise ExpatError(f"bad depth:{depth.decode()}")

        # overwrite
        """
        https://tools.ietf.org/html/rfc4918#page-77
        10.6.  Overwrite Header
              Overwrite = "Overwrite" ":" ("T" | "F")
        """
        overwrite = self.headers.get(b"overwrite")
        if overwrite == b"T":
            self.overwrite = True
        else:
            self.overwrite = False

        # timeout
        """
        https://tools.ietf.org/html/rfc4918#page-78
        10.7.  Timeout Request Header

              TimeOut = "Timeout" ":" 1#TimeType
              TimeType = ("Second-" DAVTimeOutVal | "Infinite")
                         ; No LWS allowed within TimeType
              DAVTimeOutVal = 1*DIGIT

           Clients MAY include Timeout request headers in their LOCK requests.
           However, the server is not required to honor or even consider these
           requests.  Clients MUST NOT submit a Timeout request header with any
           method other than a LOCK method.

           The "Second" TimeType specifies the number of seconds that will
           elapse between granting of the lock at the server, and the automatic
           removal of the lock.  The timeout value for TimeType "Second" MUST
           NOT be greater than 2^32-1.

           See Section 6.6 for a description of lock timeout behavior.
        """
        timeout = self.headers.get(b"timeout")
        if timeout:
            self.timeout = int(timeout[7:])
        else:
            # TODO ??? default value??
            self.timeout = 0

        # header: if
        header_if = self.headers.get(b"if")
        if header_if:
            lock_tokens_from_if = self._parser_header_if(header_if.decode("utf-8"))
            if len(lock_tokens_from_if) == 0:
                self.lock_token_is_parsed_success = False
            else:
                self.lock_token = lock_tokens_from_if[0][0]
                self.lock_token_etag = lock_tokens_from_if[0][1]

        # header: lock-token
        header_lock_token = self.headers.get(b"lock-token")
        if header_lock_token:
            lock_token = self._parser_lock_token_str(header_lock_token.decode("utf-8"))
            if lock_token is None:
                self.lock_token_is_parsed_success = False
            else:
                self.lock_token = lock_token

        # header: accept-encoding
        accept_encoding = self.headers.get(b"accept-encoding")
        if accept_encoding:
            self.accept_encoding = accept_encoding.decode("utf-8")

        # header: range
        if self.method == DAVMethod.GET:
            self._parser_header_range()

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

    @staticmethod
    def _take_string_from_brackets(data: str, start: str, end: str) -> str | None:
        begin_index = data.find(start)
        end_index = data.find(end)

        if begin_index == -1 or end_index == -1:
            return None

        return data[begin_index + 1 : end_index]

    def _parser_lock_token_str(self, data: str) -> UUID | None:
        token_str = self._take_string_from_brackets(data, "<", ">")
        if token_str is None:
            return None

        index = token_str.rfind(":")
        if index == -1:
            return None

        token_str = token_str[index + 1 :]
        try:
            token = UUID(token_str)
        except ValueError:
            return None

        return token

    def _parser_header_if(self, data: str) -> list[tuple[UUID, str | None]]:
        """
        b'if',
        b'<http://192.168.200.198:8000/litmus/lockcoll/> '
            b'(<opaquelocktoken:245ec6a9-e8e2-4c7d-acd4-740b9e301ae0> '
            b'[e24bfe34b6750624571283fcf1ed8542]) '
            b(Not <DAV:no-lock> '
            b'[e24bfe34b6750624571283fcf1ed8542])'
        """
        begin_index = data.find("(")
        if begin_index != -1:
            lock_token_path = data[:begin_index]

            tmp_str = self._take_string_from_brackets(lock_token_path, "<", ">")
            if tmp_str:
                lock_token_path = urllib.parse.urlparse(tmp_str).path
                if len(tmp_str) != 0:
                    self.lock_token_path = DAVPath(lock_token_path)

        tokens = list()
        while True:
            begin_index = data.find("(")
            end_index = data.find(")")
            if begin_index == -1 or end_index == -1:
                break

            block = data[begin_index + 1 : end_index]
            # block = self._take_string_from_brackets(data)

            if not block.startswith("Not"):
                token = self._parser_lock_token_str(block)
                etag = self._take_string_from_brackets(block, "[", "]")

                if token is None:
                    self.lock_token_is_parsed_success = False
                else:
                    tokens.append((token, etag))

            data = data[end_index + 1 :]

        return tokens

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

        if "DAV::exclusive" in data["DAV::lockscope"]:
            self.lock_scope = DAVLockScope.exclusive
        else:
            self.lock_scope = DAVLockScope.shared

        lock_owner = data["DAV::owner"]
        self.lock_owner = str(lock_owner)
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
        self.depth = DAVDepth.d1

    def _parser_header_range(self) -> None:
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Range_requests
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Range
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Content-Range
        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/If-Range # TODO
        header_range = self.headers.get(b"range")
        if header_range is None:
            return

        header_range_str = header_range.decode("utf-8").lower()
        if header_range_str[:6] != "bytes=":
            return

        content_ranges = header_range_str[6:].split(",")
        if len(content_ranges) < 1:
            return

        content_range = content_ranges[0].split("-")
        if 1 > len(content_range) > 2:
            # TODO: support multi-range
            return

        self.content_range = True
        try:
            self.content_range_start = int(content_range[0])
        except ValueError:
            return

        try:
            self.content_range_end = int(content_range[1])
        except ValueError:
            pass

        return

    def __repr__(self) -> str:
        simple_fields = ["method", "src_path", "accept_encoding"]
        rich_fields = list()

        if self.method == DAVMethod.PROPFIND:
            simple_fields += [
                "body_is_parsed_success",
                "depth",
                "propfind_only_fetch_property_name",
                "propfind_fetch_all_property",
                "propfind_only_fetch_basic",
                "propfind_basic_keys",
            ]
            rich_fields += [
                "propfind_extra_keys",
            ]

        elif self.method == DAVMethod.PROPPATCH:
            simple_fields += ["body_is_parsed_success", "depth"]
            rich_fields += [
                "proppatch_entries",
            ]

        elif self.method == DAVMethod.PUT:
            simple_fields += [
                "lock_token",
                "lock_token_path",
                "lock_token_is_parsed_success",
            ]

        elif self.method in (DAVMethod.COPY, DAVMethod.MOVE):
            simple_fields += ["dst_path", "depth", "overwrite"]

        elif self.method in (DAVMethod.LOCK, DAVMethod.UNLOCK):
            simple_fields += [
                "body_is_parsed_success",
                "depth",
                "timeout",
                "lock_scope",
                "lock_owner",
                "lock_token",
                "lock_token_path",
                "lock_token_is_parsed_success",
            ]

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
