import hashlib
from dataclasses import dataclass, field
from collections import namedtuple
from xml.parsers.expat import ExpatError
from typing import Optional, Callable, NewType, OrderedDict

import xmltodict
from prettyprinter import pprint

# from asgi_webdav.provider.base import DAVProvider

DAV_METHODS = (
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
)
DAV_METHOD = namedtuple('DAVMethodClass', DAV_METHODS)(*DAV_METHODS)

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
class DAVRequest:
    scope: dict
    receive: Callable
    send: Callable

    headers: dict[bytes]
    method: str
    src_path: str
    dst_path: Optional[str]

    data: any = None
    propfind_find_all: bool = False
    propfind_entries: list[DAVPropertyIdentity] = field(default_factory=list)
    proppatch_entries: list[DAVPropertyPatches] = field(default_factory=list)

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

    @staticmethod
    def _cut_ns_key(ns_key: str) -> tuple[str, str]:  # TODO dup in helper
        index = ns_key.rfind(':')
        if index == -1:
            return '', ns_key
        else:
            return ns_key[:index], ns_key[index + 1:]

    def parser_property_find_data(self):
        find_symbol = 'DAV::propfind'
        # print(self.data[find_symbol])

        if 'DAV::allprop' in self.data[find_symbol]:
            print('++++')
            self.propfind_find_all = True
            return

        if 'DAV::prop' not in self.data[find_symbol]:
            # TODO error
            return

        for ns_key in self.data[find_symbol]['DAV::prop']:
            self.propfind_entries.append(self._cut_ns_key(ns_key))

        # TODO default is propfind ??
        # pprint(self.propfind_entries)
        return

    def parser_property_patches_data(self):
        update_symbol = 'DAV::propertyupdate'
        # print(self.data)
        for action in self.data[update_symbol]:
            _, key = self._cut_ns_key(action)
            if key == 'set':
                method = True
            else:
                method = False

            for item in self.data[update_symbol][action]:
                if isinstance(item, OrderedDict):
                    ns_key, value = item['DAV::prop'].popitem()  # TODO items()
                else:
                    ns_key, value = self.data[update_symbol][action][
                        item].popitem()

                ns, key = self._cut_ns_key(ns_key)
                if not isinstance(value, str):
                    value = str(value)

                print(ns, key, value)
                self.proppatch_entries.append(((ns, key), value, method))

        return


@dataclass
class DistributionPassport:
    provider: any  # DAVProvider

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

    # extra
    extra: DAVPropertyExtra = field(default_factory=dict)
    extra_not_found: list[str] = field(default_factory=list)

    # lock info
    # ...

    def __post_init__(self):
        self.etag = hashlib.md5('{}{}'.format(
            self.content_length, self.last_modified
        ).encode('utf-8')).hexdigest()
