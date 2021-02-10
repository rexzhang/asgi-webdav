from typing import Optional, Union, NewType
import enum
import hashlib
from time import time
from uuid import UUID
from dataclasses import dataclass, field
from collections import namedtuple

# from asgi_webdav.provider.base import DAVProvider

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

DAVDistributeMap = NewType('DAVDistributeMap', dict[str, str])

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


class DAVPath:
    raw: str  # must start with '/' or empty
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

    def child(self, parent: 'DAVPath'):
        new_parts = self.parts[parent.count:]
        return DAVPath(
            raw='/' + '/'.join(new_parts),
            parts=new_parts,
            count=self.count - parent.count
        )

    def __hash__(self):
        return hash(self.raw)

    def __repr__(self):
        return self.raw


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


@dataclass
class DAVResponse:
    """provider.implement => DavProvider"""
    status: int  # TODO IntEnum
    message: str  # TODO bytes?


@dataclass
class DAVProperty:
    path: DAVPath
    display_name: str

    creation_date: float
    last_modified: float
    # https://tools.ietf.org/html/rfc7232#section-2.3 ETag
    etag: str = field(init=False)

    resource_type_is_dir: bool
    content_type: str  # httpd/unix-directory, text/plain...

    # file's prop
    content_length: Optional[int]
    encoding: Optional[str]

    # executable: bool = True

    # extra
    extra: DAVPropertyExtra = field(default_factory=dict)
    extra_not_found: list[str] = field(default_factory=list)

    # lock info
    # ...

    def __post_init__(self):
        self.etag = hashlib.md5('{}{}'.format(
            self.content_length, self.last_modified
        ).encode('utf-8')).hexdigest()
