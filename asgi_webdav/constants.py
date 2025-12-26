import re
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from functools import cache
from time import time
from typing import Any, TypeAlias
from uuid import UUID

import arrow

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
    def _missing_(cls, value: Any) -> "DAVUpperEnumAbc":
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
    def _missing_(cls, value: Any) -> "DAVLowerEnumAbc":
        if not isinstance(value, str):
            raise ValueError(f"Invalid {cls.__name__} value: {value}")

        try:
            return cls[value.lower()]
        except KeyError:
            return cls[cls.default_value(value).lower()]


# WebDAV protocol ---
class DAVMethod(DAVUpperEnumAbc):
    # default/fallback
    UNKNOWN = auto()

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
    # only for inside page
    POST = auto()

    @classmethod
    def default_value(cls, value: Any) -> str:
        return "UNKNOWN"

    @classmethod
    @cache
    def names_read_write(cls) -> list[str]:
        return [s for s in cls.names() if s != "UNKNOWN"]

    @classmethod
    @cache
    def names_read_only(cls) -> list[str]:
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


class DAVPath:
    raw: str  # must start with '/' or empty, and not end with '/'

    parts: list[str]
    count: int  # len(parts)

    def _update_value(self, parts: list[str], count: int) -> None:
        self.raw = "/" + "/".join(parts)
        self.parts = parts
        self.count = count

    def __init__(
        self,
        path: str | bytes | None = None,
        parts: list[str] | None = None,
        count: int | None = None,
    ):
        if path is None and parts is not None and count is not None:
            self._update_value(parts=parts, count=count)
            return

        elif not isinstance(path, (str, bytes)):
            raise Exception(f"Except path for DAVPath:{path}")

        if isinstance(path, bytes):
            path = str(path, encoding="utf-8")

        parts = list()
        for item in path.split("/"):
            if len(item) == 0:
                continue

            if item == "..":
                try:
                    parts.pop()
                except IndexError:
                    raise Exception(f"Except path for DAVPath:{path}")
                continue

            parts.append(item)

        self._update_value(parts=parts, count=len(parts))

    @property
    def parent(self) -> "DAVPath":
        return DAVPath(parts=self.parts[: self.count - 1], count=self.count - 1)

    @property
    def name(self) -> str:
        if self.count == 0:
            return "/"

        return self.parts[self.count - 1]

    def startswith(self, path: "DAVPath") -> bool:
        return self.parts[: path.count] == path.parts

    def get_child(self, parent: "DAVPath") -> "DAVPath":
        new_parts = self.parts[parent.count :]
        return DAVPath(parts=new_parts, count=self.count - parent.count)

    def add_child(self, child: "DAVPath | str") -> "DAVPath":
        if not isinstance(child, DAVPath):
            child = DAVPath(child)

        return DAVPath(
            parts=self.parts + child.parts,
            count=self.count + child.count,
        )

    def __hash__(self) -> int:
        return hash(self.raw)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DAVPath):
            return False

        return self.raw == other.raw

    def __lt__(self, other: "DAVPath") -> bool:
        return self.raw < other.raw

    def __le__(self, other: "DAVPath") -> bool:
        return self.raw > other.raw

    def __gt__(self, other: "DAVPath") -> bool:
        return self.raw <= other.raw

    def __ge__(self, other: "DAVPath") -> bool:
        return self.raw >= other.raw

    def __repr__(self) -> str:
        return f"DAVPath('{self.raw}')"

    def __str__(self) -> str:
        return self.raw


class DAVDepth(Enum):
    d0 = 0
    d1 = 1
    infinity = "infinity"


class DAVTime:
    timestamp: float

    def __init__(self, timestamp: float | None = None):
        if timestamp is None:
            timestamp = time()

        self.timestamp = timestamp
        self.arrow = arrow.get(timestamp)

    def iso_8601(self) -> str:
        return self.arrow.format(arrow.FORMAT_RFC3339)

    def http_date(self) -> str:
        # https://datatracker.ietf.org/doc/html/rfc7232#section-2.2
        # 2.2.  Last-Modified
        #
        # The "Last-Modified" header field in a response provides a timestamp
        # indicating the date and time at which the origin server believes the
        # selected representation was last modified, as determined at the
        # conclusion of handling the request.
        #
        # Last-Modified = HTTP-date
        #
        # An example of its use is
        #
        # Last-Modified: Tue, 15 Nov 1994 12:45:26 GMT

        # https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Last-Modified
        # Last-Modified:
        #   <day-name>, <day> <month> <year> <hour>:<minute>:<second> GMT
        return self.arrow.format("ddd, DD MMM YYYY HH:mm:ss ZZZ")

    def ui_display(self, timezone: str) -> str:
        return self.arrow.replace(tzinfo=timezone).format(arrow.FORMAT_W3C)

    def dav_creation_date(self) -> str:
        # format borrowed from Apache mod_webdav
        return self.arrow.format("YYYY-MM-DDTHH:mm:ssZ")

    def __repr__(self) -> str:
        return self.arrow.isoformat()


# Lock ---
class DAVLockScope(IntEnum):
    """
    https://tools.ietf.org/html/rfc4918
    14.13.  lockscope XML Element
       Name:   lockscope
       Purpose:   Specifies whether a lock is an exclusive lock, or a shared
          lock.

         <!ELEMENT lockscope (exclusive | shared) >
    """

    exclusive = 1
    shared = 2


@dataclass(slots=True)
class DAVLockInfo:
    path: DAVPath
    depth: DAVDepth
    timeout: int
    expire: float = field(init=False)
    lock_scope: DAVLockScope
    owner: str
    token: UUID  # <opaquelocktoken:UUID.__str__()>

    def __post_init__(self) -> None:
        self.update_expire()

    def update_expire(self) -> None:
        self.expire = time() + self.timeout

    def __repr__(self) -> str:
        s = ", ".join(
            [
                self.path.raw,
                self.depth.__str__(),
                self.timeout.__str__(),
                self.expire.__str__(),
                self.lock_scope.name,
                self.owner,
                self.token.hex,
            ]
        )
        return f"DAVLockInfo({s})"


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

# Response|Compression ---
DEFAULT_COMPRESSION_CONTENT_MINIMUM_LENGTH = 1024  # bytes
DEFAULT_COMPRESSION_CONTENT_TYPE_RULE = r"^application/(?:xml|json)$|^text/"


class DAVCompressionMethod(DAVLowerEnumAbc):
    RAW = auto()
    ZSTD = auto()
    DEFLATE = auto()
    GZIP = auto()


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
