import hashlib
from dataclasses import dataclass, field
from collections import namedtuple
from typing import Optional, NewType

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

    'OPTIONS',
}
DAVMethod = namedtuple('DAVMethod', DAV_METHODS)(*DAV_METHODS)

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
