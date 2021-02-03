import hashlib
from dataclasses import dataclass, field
from collections import namedtuple
from xml.parsers.expat import ExpatError
from typing import Optional, Callable

import xmltodict

# from asgi_webdav.provider import DAVProvider

DAV_METHODS = (
    # rfc4918:9.1
    'PROPFIND',  # TODO??

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
)
DAV_METHOD = namedtuple('DAVMethodClass', DAV_METHODS)(*DAV_METHODS)


@dataclass
class DAVRequest:
    scope: dict
    receive: Callable
    send: Callable

    headers: dict[bytes]
    method: str
    src_path: str
    dst_path: Optional[str]

    data: any = None

    def parser_info_from_xml_body(self, body: bytes) -> bool:
        if len(body) == 0:
            # TODO ???
            return True

        try:
            self.data = xmltodict.parse(body, process_namespaces=True)

        except ExpatError:
            print('!!!', body)  # TODO
            return False

        return True


@dataclass
class DistributionPassport:
    provider: 'asgi_webdav.provider.DAVProvider'

    src_prefix: str
    src_path: str

    dst_path: Optional[str] = None

    overwrite: bool = False
    depth: int = -1

    def parser_overwrite_from_headers(self, headers: dict[bytes]) -> None:
        if headers.get(b'overwrite', b'F') == b'F':
            self.overwrite = False
        else:
            self.overwrite = True

        return

    def parser_depth_from_headers(self, headers: dict[bytes]) -> None:
        depth = headers.get(b'depth')
        if depth is None:
            return

        try:
            depth = int(depth)
            if depth >= 0:
                self.depth = depth
                return
        except ValueError:
            pass

        if depth == b'infinity':
            self.depth = -1

        return


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

    # lock info
    # ...

    def __post_init__(self):
        self.etag = hashlib.md5('{}{}'.format(
            self.content_length, self.last_modified
        ).encode('utf-8')).hexdigest()
