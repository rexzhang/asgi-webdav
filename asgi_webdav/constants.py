from __future__ import annotations

import re
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum, auto
from functools import cache, cached_property, lru_cache
from time import time
from typing import Any, TypeAlias
from uuid import UUID
from zoneinfo import ZoneInfo

from asgi_webdav.exceptions import DAVCodingError

# Common ---


ASGIHeaders: TypeAlias = Iterable[tuple[bytes, bytes]]


class DAVUpperEnumAbc(Enum):
    # TODO: py3.11+ base on EnumStr
    """自动大写化枚举类
    .name 可以是:大写/小写/大小写混合
    .value 为 .name 的自动大写化的字符串
    .label 为初始化时写在第一位的值

    默认值为空,需要继承实现;默认不会自动匹配默认值
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._value_ = self._name_.upper()
        label = args[0]
        if not isinstance(label, str):
            self.label = str(label)
        else:
            self.label = label

    @classmethod
    def _missing_(cls, value: Any) -> DAVUpperEnumAbc:
        if not isinstance(value, str):
            raise ValueError(f"Invalid {cls.__name__} value: {value}")

        try:
            return cls[value.upper()]
        except KeyError:
            return cls[cls.default_value(value).upper()]

    @classmethod
    def default_value(cls, value: Any) -> str:
        raise ValueError(f"Invalid {cls.__name__} value: {value}")

    @classmethod
    @cache
    def names(cls) -> list[str]:
        return [item.name for item in cls]

    @classmethod
    @cache
    def values(cls) -> list[str]:
        return [item.value for item in cls]

    @classmethod
    @cache
    def value_label_mapping(cls) -> dict[str, str]:
        return {item.value: item.label for item in cls}


class DAVLowerEnumAbc(DAVUpperEnumAbc):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._value_ = self._name_.lower()
        label = args[0]
        if not isinstance(label, str):
            self.label = str(label)
        else:
            self.label = label

    @classmethod
    def _missing_(cls, value: Any) -> DAVLowerEnumAbc:
        if not isinstance(value, str):
            raise ValueError(f"Invalid {cls.__name__} value: {value}")

        try:
            return cls[value.lower()]
        except KeyError:
            return cls[cls.default_value(value).lower()]


# WebDAV protocol ---
class DAVMethod(DAVUpperEnumAbc):
    # webdav methods ---
    # rfc4918:9.1
    PROPFIND = auto()
    # rfc4918:9.2
    PROPPATCH = auto()
    # rfc4918:9.3
    MKCOL = auto()
    # rfc4918:9.4
    GET = auto()
    HEAD = auto()
    # rfc4918:9.6
    DELETE = auto()
    # rfc4918:9.7
    PUT = auto()
    # rfc4918:9.8
    COPY = auto()
    # rfc4918:9.9
    MOVE = auto()
    # rfc4918:9.10
    LOCK = auto()
    # rfc4918:9.11
    UNLOCK = auto()
    OPTIONS = auto()

    # other ---
    # default/fallback
    UNKNOWN = auto()
    # only for inside page
    POST = auto()

    @classmethod
    def default_value(cls, value: Any) -> str:
        return "UNKNOWN"

    @classmethod
    def names_webdav_read_write(cls) -> list[str]:
        return [
            "PROPFIND",
            "PROPPATCH",
            "MKCOL",
            "GET",
            "HEAD",
            "DELETE",
            "PUT",
            "COPY",
            "MOVE",
            "LOCK",
            "UNLOCK",
            "OPTIONS",
        ]

    @classmethod
    def names_webdav_read_only(cls) -> list[str]:
        return ["PROPFIND", "GET", "HEAD", "OPTIONS"]


class DAVHeaders:
    data: dict[bytes, bytes]

    def __init__(self, data: ASGIHeaders | None = None):
        if data is None:
            self.data = dict()
            return

        self.data = dict(data)

    def get(self, key: bytes) -> bytes | None:
        return self.data.get(key)

    def __getitem__(self, key: bytes) -> bytes | None:
        return self.data.get(key)

    def __setitem__(self, key: bytes, value: bytes) -> None:
        self.data[key] = value

    def __contains__(self, item: bytes) -> bool:
        return item in self.data

    def update(self, new_data: dict[bytes, bytes]) -> None:
        self.data.update(new_data)

    def list(self) -> list[tuple[bytes, bytes]]:
        return list(self.data.items())

    def __repr__(self) -> str:  # pragma: no cover
        return self.data.__repr__()


DAVPathCacheSize = 1024


class DAVPath:
    parts: list[str]
    parts_count: int

    @cached_property
    def raw(self) -> str:
        """start with '/', end without '/'"""
        return "/" + "/".join(self.parts)

    @cached_property
    def raw_count(self) -> int:
        return len(self.raw)

    @cached_property
    def hash_value(self) -> int:
        return hash(self.raw)

    def __init__(
        self,
        path: str | bytes | None = None,
        parts: list[str] | None = None,
        count: int | None = None,
    ):
        match path, parts, count:
            case None, list(), int():
                self.parts = parts
                self.parts_count = count
                return

            case str(), None, None:
                new_path = path

            case bytes(), None, None:
                new_path = path.decode()

            case None, None, None:
                new_path = "/"

            case _, _, _:
                raise DAVCodingError(f"Incorrect path value for DAVPath: {path!r}")

        if new_path == "/":
            self.parts = []
            self.parts_count = 0
            return

        new_path = new_path.strip("/")
        new_parts: list[str] = list()
        for item in new_path.split("/"):
            if len(item) == 0 or item.isspace() or item in {".", ".."}:
                raise ValueError(f"incorrect path value for DAVPath: {path!r}")

            new_parts.append(item)

        self.parts = new_parts
        self.parts_count = len(new_parts)

    @property
    def parent(self) -> DAVPath:
        return DAVPath(
            parts=self.parts[: self.parts_count - 1], count=self.parts_count - 1
        )

    @cached_property
    def name(self) -> str:
        if self.parts_count == 0:
            return "/"

        return self.parts[self.parts_count - 1]

    @lru_cache(DAVPathCacheSize)
    def is_parent_of(self, path: DAVPath) -> bool:
        if self.parts_count == 0 and path.parts_count > 0:
            return True

        parent, child = path.raw[: self.raw_count], path.raw[self.raw_count :]

        if parent != self.raw:
            return False

        if child.startswith("/"):
            return True

        return False

    @lru_cache(DAVPathCacheSize)
    def is_parent_of_or_is_self(self, path: DAVPath) -> bool:
        """is parent of or is the same/self"""
        if self.parts_count == 0:
            return True

        if self == path:
            return True

        parent, child = path.raw[: self.raw_count], path.raw[self.raw_count :]

        if parent != self.raw:
            return False

        if child.startswith("/"):
            return True

        return False

    def get_child(self, parent: DAVPath) -> DAVPath:
        return DAVPath(
            parts=self.parts[parent.parts_count :],
            count=self.parts_count - parent.parts_count,
        )

    def add_child(self, child: DAVPath | str) -> DAVPath:
        if not isinstance(child, DAVPath):
            child = DAVPath(child)

        return DAVPath(
            parts=self.parts + child.parts,
            count=self.parts_count + child.parts_count,
        )

    def __hash__(self) -> int:
        return self.hash_value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DAVPath):
            return False

        return self.hash_value == other.hash_value

    def __lt__(self, other: DAVPath) -> bool:
        return self.raw < other.raw

    def __le__(self, other: DAVPath) -> bool:
        return self.raw <= other.raw

    def __gt__(self, other: DAVPath) -> bool:
        return self.raw > other.raw

    def __ge__(self, other: DAVPath) -> bool:
        return self.raw >= other.raw

    def __repr__(self) -> str:
        return f"DAVPath('{self.raw}')"

    def __str__(self) -> str:
        return self.raw


class DAVDepth(Enum):
    """
    - https://datatracker.ietf.org/doc/html/rfc4918#section-14.4
    Name:   depth

    Purpose:   Used for representing depth values in XML content (e.g.,
        in lock information).

    Value:   "0" | "1" | "infinity"
    """

    ZERO = "0"
    ONE = "1"
    INFINITY = "infinity"


class DAVTime:
    data: datetime
    timestamp: float

    def __init__(self, timestamp: float | None = None):
        if timestamp is None:
            self.data = datetime.now(timezone.utc)
            self.timestamp = self.data.timestamp()
        else:
            self.timestamp = timestamp
            self.data = datetime.fromtimestamp(timestamp, tz=timezone.utc)

    @cached_property
    def iso_8601(self) -> str:
        # - https://datatracker.ietf.org/doc/html/rfc3339#section-5.6
        # 5.8. Examples
        #
        #    Here are some examples of Internet date/time format.
        #       1985-04-12T23:20:50.52Z
        #
        #    This represents 20 minutes and 50.52 seconds after the 23rd hour of
        #    April 12th, 1985 in UTC.
        #       1996-12-19T16:39:57-08:00
        #
        #    This represents 39 minutes and 57 seconds after the 16th hour of
        #    December 19th, 1996 with an offset of -08:00 from UTC (Pacific
        #    Standard Time).  Note that this is equivalent to 1996-12-20T00:39:57Z
        #    in UTC.
        #       1990-12-31T23:59:60Z
        #
        #    This represents the leap second inserted at the end of 1990.
        #       1990-12-31T15:59:60-08:00
        #
        #    This represents the same leap second in Pacific Standard Time, 8
        #    hours behind UTC.
        #       1937-01-01T12:00:27.87+00:20
        #
        #    This represents the same instant of time as noon, January 1, 1937,
        #    Netherlands time.  Standard time in the Netherlands was exactly 19
        #    minutes and 32.13 seconds ahead of UTC by law from 1909-05-01 through
        #    1937-06-30.  This time zone cannot be represented exactly using the
        #    HH:MM format, and this timestamp uses the closest representable UTC
        #    offset.
        return self.data.isoformat()

    @cached_property
    def w3c(self) -> str:
        # "1970-01-01 00:00:00+00:00"
        return self.data.isoformat(" ")

    @cached_property
    def http_date(self) -> str:
        # - https://datatracker.ietf.org/doc/html/rfc9110.html#section-5.6.7
        # 5.6.7. Date/Time Formats
        #
        # Prior to 1995, there were three different formats commonly used by servers to communicate timestamps. For compatibility with old implementations, all three are defined here. The preferred format is a fixed-length and single-zone subset of the date and time specification used by the Internet Message Format [RFC5322].
        #   HTTP-date    = IMF-fixdate / obs-date
        #
        # An example of the preferred format is
        #   Sun, 06 Nov 1994 08:49:37 GMT    ; IMF-fixdate
        #
        # Examples of the two obsolete formats are
        #   Sunday, 06-Nov-94 08:49:37 GMT   ; obsolete RFC 850 format
        #   Sun Nov  6 08:49:37 1994         ; ANSI C's asctime() format

        # https://datatracker.ietf.org/doc/html/rfc7232#section-2.2
        # 2.2.  Last-Modified
        #
        # The "Last-Modified" header field in a response provides a timestamp
        # indicating the date and time at which the origin server believes the
        # selected representation was last modified, as determined at the
        # conclusion of handling the request.
        #   Last-Modified = HTTP-date
        #
        # An example of its use is
        #   Last-Modified: Tue, 15 Nov 1994 12:45:26 GMT

        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Last-Modified
        # Last-Modified:
        #   <day-name>, <day> <month> <year> <hour>:<minute>:<second> GMT
        return self.data.strftime("%a, %d %b %Y %H:%M:%S GMT")

    def display(self, timezone: ZoneInfo) -> str:
        return self.data.astimezone(timezone).isoformat(" ")

    def __repr__(self) -> str:
        return self.data.__repr__()


# Lock ---

# --- common
# - https://datatracker.ietf.org/doc/html/rfc4918#section-10.7
# The timeout value for TimeType "Second" MUST NOT be greater than 2^32-1.
DAVLockTimeoutMaxValue = 2**32 - 1  # TODO: move into config ???


class DAVLockScope(Enum):
    """
    https://tools.ietf.org/html/rfc4918
    14.13.  lockscope XML Element
       Name:   lockscope
       Purpose:   Specifies whether a lock is an exclusive lock, or a shared
          lock.

         <!ELEMENT lockscope (exclusive | shared) >
    """

    EXCLUSIVE = "exclusive"
    SHARED = "shared"


# --- lock:request:header
class DAVRequestIfConditionType(IntEnum):
    TOKEN = auto()
    ETAG = auto()
    NO_LOCK = auto()  # for: Not <DAV:no-lock>


@dataclass(slots=True)
class DAVRequestIfCondition:
    is_not: bool

    type: DAVRequestIfConditionType
    data: str


@dataclass(slots=True)
class DAVRequestIf:
    res_path: DAVPath  # 针对 No-tag-list, 使用 src_path 填充

    # list outside(L1): OR, list inside(L2): AND
    # [Condition1, Condition2],  # OR 逻辑中的第一个列表 [AND 关系]
    # [Condition3]               # OR 逻辑中的第二个列表
    conditions: list[list[DAVRequestIfCondition]]


# --- lock:request:body
@dataclass(slots=True)
class DAVRequestBodyLock:
    scope: DAVLockScope
    owner: str


# --- lock:locker
@dataclass
class DAVLockObj:
    owner: str

    # path
    path: DAVPath
    depth: DAVDepth  # only support: DAVDepth.d0, DAVDepth.infinity

    # lock
    token: UUID  # <opaquelocktoken:UUID.__str__()>
    scope: DAVLockScope

    # expire
    timeout: int
    _expire: float = field(init=False)

    @cached_property
    def hash_value(self) -> int:
        return hash(self.token)

    def __post_init__(self) -> None:
        self.update_expire()

    def update_expire(self) -> None:
        self._expire = time() + self.timeout

    def is_expired(self, now: float | None = None) -> bool:
        if now is None:
            now = time()

        return self._expire <= now

    def is_locking_path(self, path: DAVPath) -> bool:
        """Check if the path is locked by the current lock"""
        match self.depth:
            case DAVDepth.ZERO:
                return self.path == path
            case DAVDepth.INFINITY:
                return self.path.is_parent_of_or_is_self(path)
            case _:  # pragma: no cover
                raise DAVCodingError(f"invalid depth: {self.depth}")

    def __hash__(self) -> int:
        return self.hash_value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DAVLockObj):
            return False

        return self.hash_value == other.hash_value

    def __repr__(self) -> str:
        s = ", ".join(
            [
                self.owner,
                self.path.raw,
                self.depth.__str__(),
                self.token.hex,
                self.scope.name,
                self.timeout.__str__(),
                self._expire.__str__(),
            ]
        )
        return f"DAVLockInfo({s})"


@dataclass(slots=True)
class DAVLockObjSet:
    lock_scope: DAVLockScope
    _data: set[DAVLockObj]

    @property
    def data(self) -> set[DAVLockObj]:
        return self._data

    def __contains__(self, lock_obj: DAVLockObj) -> bool:
        return lock_obj in self._data

    def add(self, lock_obj: DAVLockObj) -> None:
        self._data.add(lock_obj)

    def remove(self, lock_obj: DAVLockObj) -> None:
        self._data.remove(lock_obj)

    def is_empty(self) -> bool:
        return not self._data

    def __repr__(self) -> str:
        return f"DAVLockObjSet({self.lock_scope.name}, {len(self._data)})"


# Property ---
DAV_PROPERTY_BASIC_KEYS = {
    # Identify
    "displayname",
    "getetag",
    # Date Time
    "creationdate",
    "getlastmodified",
    # File Properties
    "getcontenttype",
    "getcontentlength",
    # 'getcontentlanguage',
    # is dir
    "resourcetype",
    "encoding",
    # 'supportedlock', 'lockdiscovery'
    # 'executable'
}

# (ns, key)
DAVPropertyIdentity: TypeAlias = tuple[str, str]
# (DAVPropertyIdentity, value, set<True>/remove<False>)
DAVPropertyPatchEntry: TypeAlias = tuple[DAVPropertyIdentity, str, bool]


# Range ---
# - 从 0 开始计数
# - 左右均为闭区间
class DAVRangeType(IntEnum):
    RANGE = auto()
    SUFFIX = auto()


# Range|Request ---
@dataclass(slots=True)
class DAVRequestRange:
    type: DAVRangeType
    range_start: int | None = None  # >=1
    range_end: int | None = None  # > range_start, <= file_size -1
    suffix_length: int | None = None  # <= file_size


# Range|Response ---
@dataclass(slots=True)
class DAVResponseContentRange:
    type: DAVRangeType
    content_start: int
    content_end: int
    file_size: int

    @property
    def content_length(self) -> int:
        return self.content_end - self.content_start + 1


# Response ---
RESPONSE_DATA_BLOCK_SIZE = 64 * 1024


class DAVResponseContentType(Enum):
    ANY = 0  # 涵盖包括所有文件类型
    HTML = 1
    XML = 2


# (body<bytes>, more_body<bool>)
DAVResponseBodyGenerator: TypeAlias = AsyncGenerator[tuple[bytes, bool], None]


class DAVSenderName(DAVLowerEnumAbc):
    RAW = auto()
    ZSTD = auto()
    DEFLATE = auto()
    GZIP = auto()


# Response|Compression ---
DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH = 1024  # bytes
DEFAULT_COMPRESSION_CONTENT_TYPE_RULE = r"^application/(?:xml|json)$|^text/"


class DAVCompressLevel(Enum):
    """
    http://mattmahoney.net/dc/text.html
    https://quixdb.github.io/squash-benchmark/
    https://sites.google.com/site/powturbo/home/benchmark
    """

    FAST = "fast"
    RECOMMEND = "recommend"
    BEST = "best"


# Authentication ---

DEFAULT_USERNAME = "username"
DEFAULT_PASSWORD = "password"
DEFAULT_USERNAME_ANONYMOUS = "anonymous"
DEFAULT_PASSWORD_ANONYMOUS = ""
DEFAULT_PERMISSIONS = ["+"]

# -1 means cache does not expire, 0 mean cache is disabled,
# >0 is seconds until cache entry expires
DEFAULT_HTTP_BASIC_AUTH_CACHE_TIMEOUT = -1


@dataclass(slots=True)
class DAVUser:
    username: str
    password: str
    permissions: list[str]

    admin: bool
    anonymous: bool = False

    permissions_allow: list[str] = field(default_factory=list)
    permissions_deny: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for permission in self.permissions:
            if permission[0] == "+":
                self.permissions_allow.append(permission[1:])
            elif permission[0] == "-":
                self.permissions_deny.append(permission[1:])
            else:
                raise

    def check_paths_permission(self, paths: list[DAVPath]) -> bool:
        for path in paths:
            allow = False
            for permission in self.permissions_allow:  # allow: or
                m = re.match(permission, path.raw)
                if m is not None:
                    allow = True
                    break

            if not allow:
                return False

        for path in paths:
            allow = True
            for permission in self.permissions_deny:  # deny: and
                m = re.match(permission, path.raw)
                if m is not None:
                    allow = False
                    break

            if not allow:
                return False

        return True

    def __str__(self) -> str:
        return "{}, allow:{}, deny:{}".format(
            self.username, self.permissions_allow, self.permissions_deny
        )


# Extra ---

CLIENT_USER_AGENT_RE_FIREFOX = r"^Mozilla/5.0.+Gecko/.+Firefox/"
CLIENT_USER_AGENT_RE_SAFARI = r"^Mozilla/5.0.+Version/.+Safari/"
CLIENT_USER_AGENT_RE_CHROME = r"^Mozilla/5.0.+Chrome/.+Safari/"
CLIENT_USER_AGENT_RE_MACOS_FINDER = r"^WebDAVFS/"
CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER = r"^Microsoft-WebDAV-MiniRedir/"

DEFAULT_FILENAME_CONTENT_TYPE_MAPPING = {
    # coding
    "README": "text/plain",
    "LICENSE": "text/plain",
    ".gitignore": "text/plain",
    ".coveragerc": "text/plain",
    # docker
    "Dockerfile": "text/plain",
    ".dockerignore": "text/plain",
}

DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING = {
    ".cfg": "text/plain",
    ".md": "text/plain",
    ".toml": "text/plain",
    ".yaml": "text/plain",
    ".yml": "text/plain",
    # code source
    ".php": "text/plain",
}

# https://en.wikipedia.org/wiki/.DS_Store
# https://en.wikipedia.org/wiki/AppleSingle_and_AppleDouble_formats
# https://en.wikipedia.org/wiki/Windows_thumbnail_cache

HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV = r".+\.WebDAV$"
HIDE_FILE_IN_DIR_RULE_MACOS = r"^\.DS_Store$|^\._.+"
HIDE_FILE_IN_DIR_RULE_WINDOWS = r"^Thumbs\.db$"
HIDE_FILE_IN_DIR_RULE_SYNOLOGY = r"^#recycle$|^@eaDir$"

DEFAULT_HIDE_FILE_IN_DIR_RULES = {
    # Basic Rule
    "": "|".join([HIDE_FILE_IN_DIR_RULE_ASGI_WEBDAV, HIDE_FILE_IN_DIR_RULE_SYNOLOGY]),
    # Client Special Rule
    CLIENT_USER_AGENT_RE_FIREFOX: "|".join(
        [HIDE_FILE_IN_DIR_RULE_MACOS, HIDE_FILE_IN_DIR_RULE_WINDOWS]
    ),
    CLIENT_USER_AGENT_RE_SAFARI: "|".join(
        [HIDE_FILE_IN_DIR_RULE_MACOS, HIDE_FILE_IN_DIR_RULE_WINDOWS]
    ),
    CLIENT_USER_AGENT_RE_CHROME: "|".join(
        [HIDE_FILE_IN_DIR_RULE_MACOS, HIDE_FILE_IN_DIR_RULE_WINDOWS]
    ),
    CLIENT_USER_AGENT_RE_MACOS_FINDER: HIDE_FILE_IN_DIR_RULE_WINDOWS,
    CLIENT_USER_AGENT_RE_WINDOWS_EXPLORER: HIDE_FILE_IN_DIR_RULE_MACOS,
}


# Development ---


class LoggingLevel(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class DevMode(Enum):
    DEV = 1
    LIMTUS = 2


@dataclass(slots=True)
class AppEntryParameters:
    bind_host: str | None = None
    bind_port: int | None = None

    config_file: str | None = None
    admin_user: tuple[str, str] | None = None
    root_path: str | None = None

    dev_mode: DevMode | None = None

    logging_display_datetime: bool = True
    logging_use_colors: bool = True
