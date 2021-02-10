from typing import Optional, NewType
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


@dataclass
class DAVLockInfo:
    path: str
    depth: int
    timeout: int
    expire: float = field(init=False)
    scope: DAVLockScope
    owner: str
    token: UUID  # opaquelocktoken

    def __post_init__(self):
        self.path = self.path.rstrip('/')
        self.update_expire()

    def update_expire(self):
        self.expire = time() + self.timeout


@dataclass
class DAVPassport:
    """ Distribute Information
    DAVDistributor => DavProvider => provider.implement
    """
    provider: any  # DAVProvider

    src_prefix: str
    src_path: str

    dst_path: Optional[str] = None


@dataclass
class DAVResponse:
    """provider.implement => DavProvider"""
    status: int  # TODO IntEnum
    message: str  # TODO bytes?


@dataclass
class DAVProperty:
    path: str
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
