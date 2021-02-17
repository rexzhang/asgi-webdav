from typing import Optional, Union, NewType, Callable
import enum
import hashlib
from time import time
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass, field
from collections import namedtuple

LOGGING_CONFIG = {
    'version': 1,
    'formatters': {
        'webdav': {
            'format': '%(asctime)s %(levelname)s: [%(name)s] %(message)s'
        },
        'uvicorn': {
            'format': '%(asctime)s %(levelname)s: [uvicorn] %(message)s'
        },
    },
    'handlers': {
        'webdav': {
            'class': 'logging.StreamHandler',
            'formatter': 'webdav',
            'level': 'DEBUG',
        },
        'uvicorn': {
            'class': 'logging.StreamHandler',
            'formatter': 'uvicorn',
            'level': 'INFO',
        },
    },
    'loggers': {
        'asgi_webdav': {
            'handlers': ['webdav', ],
            'propagate': False,
            'level': 'INFO',
        },
        'uvicorn': {
            'handlers': ['uvicorn', ],
            'propagate': False,
            'level': 'INFO',
        },
    },
    # 'root': {
    #     'handlers': ['console', ],
    #     'propagate': False,
    #     'level': 'INFO',
    # },
}

DAV_METHODS = {
    # rfc4918:9.1
    'PROPFIND',
    # rfc4918:9.2
    'PROPPATCH',

    # rfc4918:9.3
    'MKCOL',
    # rfc4918:9.4
    'GET', 'HEAD',
    # rfc4918:9.6
    'DELETE',
    # rfc4918:9.7
    'PUT',

    # rfc4918:9.8
    'COPY',
    # rfc4918:9.9
    'MOVE',

    # rfc4918:9.10
    'LOCK',
    # rfc4918:9.11
    'UNLOCK',

    'OPTIONS',
}
DAVMethod = namedtuple('DAVMethodClass', DAV_METHODS)(*DAV_METHODS)


class DAVPath:
    raw: str  # must start with '/' or empty, and not end with '/'
    # weight: int  # len(raw)

    parts: list[str]
    count: int  # len(parts)

    def __init__(
        self, raw: Union[str, bytes],
        parts: list[str] = None, count: int = None
    ):
        if not isinstance(raw, (str, bytes)):
            raise Exception('Except raw path for DAVPath:{}'.format(raw))

        if isinstance(raw, bytes):
            raw = str(raw, encoding='utf-8')

        if len(raw) > 0 and ('//' in raw or '..' in raw):
            raise Exception('Except raw path for DAVPath:{}'.format(raw))

        raw = raw.rstrip('/')
        if parts and count:
            self.raw = raw
            self.parts = parts
            self.count = count
            return

        self.raw = raw
        self.parts = raw.split('/')
        self.count = len(self.parts)

    def startswith(self, path: 'DAVPath') -> bool:
        # for index in range(parent.count):
        #     if self.parts[index] != parent.parts[index]:
        #         return False
        #
        # return True
        return self.parts[:path.count] == path.parts

    def child(self, parent: 'DAVPath') -> 'DAVPath':
        new_parts = self.parts[parent.count:]
        return DAVPath(
            raw='/' + '/'.join(new_parts),
            parts=new_parts,
            count=self.count - parent.count
        )

    def append_child(self, child: str) -> 'DAVPath':
        if '//' in child or '..' in child:
            raise Exception('Except raw path for DAVPath:{}'.format(child))

        child = child.strip('/').rstrip('/')
        child_parts = child.split('/')
        return DAVPath(
            raw=self.raw + '/' + child,
            parts=self.parts + child_parts,
            count=self.count + len(child_parts),
        )

    def __hash__(self):
        return hash(self.raw)

    def __repr__(self):
        return self.raw

    def __str__(self):
        return self.raw


class DAVLockScope(enum.IntEnum):
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


@dataclass
class DAVLockInfo:
    path: DAVPath
    depth: int
    timeout: int
    expire: float = field(init=False)
    scope: DAVLockScope
    owner: str
    token: UUID  # opaquelocktoken

    def __post_init__(self):
        self.update_expire()

    def update_expire(self):
        self.expire = time() + self.timeout


@dataclass
class DAVPassport:
    """ Distribute Information
    DAVDistributor => DavProvider => provider.implement
    """
    provider: any  # DAVProvider

    src_prefix: DAVPath
    src_path: DAVPath

    dst_path: Optional[DAVPath] = None


DAV_PROPERTY_BASIC_KEYS = {
    'displayname', 'getetag',
    'creationdate', 'getlastmodified',
    'getcontentlength', 'getcontenttype',  # 'getcontentlanguage'
    'resourcetype',
    # 'supportedlock', 'lockdiscovery'
    # 'executable'
}

DAVPropertyIdentity = NewType(
    # (namespace, key)
    'DAVPropertyIdentity', tuple[str, str]
)
DAVPropertyExtra = NewType(
    'DAVPropertyExtra', dict[DAVPropertyIdentity, str]
)
DAVPropertyPatches = NewType(
    'DAVPropertyPatches', list[
        # (DAVPropertyIdentity, value, set<True>/remove<False>)
        tuple[DAVPropertyIdentity, str, bool]
    ]
)


# @dataclass
# class DAVPropertyBasic:
#     path: DAVPath
#     display_name: str
#
#     creation_date: float
#     last_modified: float
#     # https://tools.ietf.org/html/rfc7232#section-2.3 ETag
#     etag: str = field(init=False)
#
#     resource_type_is_dir: bool
#     content_type: str  # httpd/unix-directory, text/plain...
#
#     # file's prop
#     content_length: Optional[int]
#     encoding: Optional[str]
#
#     # executable: bool = True
#
#     # extra
#     extra: DAVPropertyExtra = field(default_factory=dict)
#     extra_not_found: list[str] = field(default_factory=list)
#
#     # lock info
#     # ...
#
#     def __post_init__(self):
#         self.etag = hashlib.md5('{}{}'.format(
#             self.content_length, self.last_modified
#         ).encode('utf-8')).hexdigest()


class DAVProperty:
    path: DAVPath  # = passport.src_path + child ; child maybe is empty
    is_collection: bool

    # basic: bool
    # basic_keys: list[str]
    basic_data: dict[str, str]

    extra: bool
    # extra_keys: list[str]
    extra_data: dict[DAVPropertyIdentity, str]
    extra_not_found: list[str]


class DAVResponse:
    """provider.implement => DavProvider"""
    status: int
    message: bytes
    headers: list[tuple[bytes, bytes]]

    def __init__(
        self, status: int, message: bytes = b'',
        headers: Optional[list[tuple[bytes, bytes]]] = None  # extend headers
    ):
        self.status = status
        self.message = message
        self.headers = [
            # (b'Content-Type', b'text/html'),
            (b'Content-Type', b'application/xml'),
            (b'Content-Length', str(len(message)).encode('utf-8')),
            (b'Date', datetime.utcnow().isoformat().encode('utf-8')),
        ]
        if headers:
            self.headers += headers

    async def send_in_one_call(self, send: Callable):
        await send({
            'type': 'http.response.start',
            'status': self.status,
            'headers': self.headers,
        })
        await send({
            'type': 'http.response.body',
            'body': self.message,
        })

        return
