from typing import Optional, Coroutine
from dataclasses import dataclass
from collections import namedtuple

from asgi_webdav.provider import DAVProvider

DAV_METHODS = (
    'OPTIONS',
    'HEAD', 'PROPFIND',
    'DELETE', 'MKCOL', 'PUT', 'GET',
    'COPY', 'MOVE'
)
DAV_METHOD = namedtuple('DAVMethodClass', DAV_METHODS)(*DAV_METHODS)


@dataclass
class DAVRequest:
    scope: dict
    receive: Coroutine
    send: Coroutine

    headers: dict[bytes]
    method: str
    src_path: str
    dst_path: Optional[str]


@dataclass
class DistributionPassport:
    provider: DAVProvider

    src_prefix: str
    src_path: str

    dst_path: Optional[str] = None

    overwrite: bool = False
    depth: Optional[int] = None

    def parser_info_from_headers(self, headers: dict[bytes]):
        if headers.get(b'overwrite', b'F') == b'F':
            self.overwrite = False
        else:
            self.overwrite = True

        depth = headers.get(b'depth')
        if depth:
            if depth == b'infinity':
                self.depth = -1
            if depth == b'0':
                self.depth = 0


class DAVProperty:
    pass
