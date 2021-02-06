from dataclasses import dataclass, field
from typing import Callable, Optional, OrderedDict
from urllib.parse import urlparse

import xmltodict
from pyexpat import ExpatError

from asgi_webdav.constants import (
    DAV_METHODS,
    DAVPropertyIdentity,
    DAVPropertyPatches,
)
from asgi_webdav.helpers import receive_all_data_in_one_call
from asgi_webdav.exception import NotASGIRequestException


@dataclass
class DAVRequest:
    """Information from Request
    DAVDistributor => DavProvider => provider.implement
    """
    scope: dict
    receive: Callable
    send: Callable

    # header's info
    method: str = field(init=False)
    headers: dict[bytes] = field(init=False)
    src_path: str = field(init=False)
    dst_path: Optional[str] = field(init=False)
    overwrite: bool = field(init=False)
    depth: int = -1  # default's infinity

    # body' info
    # body: Optional[bytes] = field(init=False)
    propfind_find_all: bool = False
    propfind_entries: list[DAVPropertyIdentity] = field(default_factory=list)
    proppatch_entries: list[DAVPropertyPatches] = field(default_factory=list)

    def __post_init__(self):
        self.method = self.scope.get('method')
        if self.method not in DAV_METHODS:
            raise NotASGIRequestException(
                'method:{} is not support method'.format(self.method)
            )

        self.headers = dict(self.scope.get('headers'))

        # path
        self.src_path = self.scope.get('path')
        if len(self.src_path) == 0:
            self.src_path = '/'

        self.dst_path = self.headers.get(b'destination')
        if self.dst_path:
            self.dst_path = str(urlparse(
                self.headers.get(b'destination')
            ).path, encoding='utf8')

        # overwrite
        """
        https://tools.ietf.org/html/rfc4918#page-77
        10.6.  Overwrite Header
              Overwrite = "Overwrite" ":" ("T" | "F")
        """
        if self.headers.get(b'overwrite', b'F') == b'F':
            self.overwrite = False
        else:
            self.overwrite = True

        # depth
        """
        https://tools.ietf.org/html/rfc4918
        14.4.  depth XML Element
        Name:   depth
        Purpose:   Used for representing depth values in XML content (e.g.,
          in lock information).
        Value:   "0" | "1" | "infinity"
        <!ELEMENT depth (#PCDATA) >
        """
        depth = self.headers.get(b'depth')
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

    @staticmethod
    def _parser_xml_data(data: bytes) -> Optional[OrderedDict]:
        try:
            data = xmltodict.parse(data, process_namespaces=True)

        except ExpatError:
            print('!!!', data)  # TODO
            return None

        return data

    @staticmethod
    def _cut_ns_key(ns_key: str) -> tuple[str, str]:  # TODO dup in helper
        index = ns_key.rfind(':')
        if index == -1:
            return '', ns_key
        else:
            return ns_key[:index], ns_key[index + 1:]

    async def parser_propfind_request(self) -> bool:
        body = await receive_all_data_in_one_call(self.receive)
        """A client may choose not to submit a request body.  An empty PROPFIND
   request body MUST be treated as if it were an 'allprop' request.
        """
        if len(body) == 0:
            self.propfind_find_all = True
            return True

        data = self._parser_xml_data(body)
        if data is None:
            return False

        find_symbol = 'DAV::propfind'

        if 'DAV::allprop' in data[find_symbol]:
            print('++++')
            self.propfind_find_all = True
            return True

        if 'DAV::prop' not in data[find_symbol]:
            # TODO error
            return False

        for ns_key in data[find_symbol]['DAV::prop']:
            self.propfind_entries.append(self._cut_ns_key(ns_key))

        # TODO default is propfind ??
        return True

    async def parser_proppatch_request(self) -> bool:
        body = await receive_all_data_in_one_call(self.receive)
        data = self._parser_xml_data(body)
        if data is None:
            return False

        update_symbol = 'DAV::propertyupdate'
        for action in data[update_symbol]:
            _, key = self._cut_ns_key(action)
            if key == 'set':
                method = True
            else:
                method = False

            for item in data[update_symbol][action]:
                if isinstance(item, OrderedDict):
                    ns_key, value = item['DAV::prop'].popitem()  # TODO items()
                else:
                    ns_key, value = data[update_symbol][action][
                        item].popitem()

                ns, key = self._cut_ns_key(ns_key)
                if not isinstance(value, str):
                    value = str(value)

                print(ns, key, value)
                self.proppatch_entries.append(((ns, key), value, method))

        return True
