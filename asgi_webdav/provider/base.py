from typing import Optional, Callable

import xmltodict
from prettyprinter import pprint

from asgi_webdav.constants import (
    DAVRequest,
    DistributionPassport,
    DAVProperty,
    DAVPropertyIdentity,
    DAVPropertyPatches,
)
from asgi_webdav.helpers import (
    DateTime,
    send_response_in_one_call,
)


class DAVProvider:
    @staticmethod
    def _create_ns_key_with_id(
        ns_map: dict[str, str], ns: str, key: str
    ) -> str:
        if len(ns) == 0:
            # no namespace
            return key

        ns_id = ns_map.setdefault(ns, 'ns{}'.format(len(ns_map) + 1))
        return '{}:{}'.format(ns_id, key)

    @staticmethod
    def _create_property_response_xml(response: any) -> bytes:
        data = {
            'D:multistatus': {
                '@xmlns:D': 'DAV:',
                'D:response': response,
            }
        }

        # TODO xmltodict have bug:
        #   '\n'
        x = xmltodict.unparse(
            data, short_empty_elements=True
        ).replace('\n', '')
        return bytes(x, encoding='utf-8')

    def _create_propfind_response(
        self, properties_list: list[DAVProperty], prefix: str
    ) -> bytes:
        response = list()
        ns_map = dict()
        ns_number = 0
        for properties in properties_list:
            href = '{}{}'.format(prefix, properties.path)

            if properties.resource_type_is_dir:
                resource_type = {'D:collection': None}
            else:
                resource_type = None

            item = {
                'D:href': href,
                'D:propstat': [{
                    'D:prop': {
                        'D:getcontenttype': properties.content_type,
                        'D:displayname': properties.display_name,
                        'D:creationdate': DateTime(
                            properties.creation_date
                        ).iso_8601(),
                        'D:getetag': properties.etag,
                        'D:getlastmodified': DateTime(
                            properties.last_modified
                        ).iso_850(),
                        'D:resourcetype': resource_type,

                        # 'D:supportedlock': {
                        #     'D:lockentry': [
                        #         {
                        #             'D:lockscope': {'D:exclusive': ''},
                        #             'D:locktype': {'D:write': ''}
                        #         },
                        #         {
                        #             'D:lockscope': {'D:shared': None},
                        #             'D:locktype': {'D:write': None}
                        #         }
                        #     ]
                        # },
                        # 'D:lockdiscovery': None,
                    },
                    'D:status': 'HTTP/1.1 200 OK',
                }],
            }

            for (ns, key), value in properties.extra.items():
                ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                item['D:propstat'][0]['D:prop'][ns_id] = value

            if len(properties.extra_not_found) > 0:
                not_found = dict()
                for ns, key in properties.extra_not_found:
                    ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                    not_found[ns_id] = None

                not_found = {
                    'D:prop': not_found,
                    'D:status': 'HTTP/1.1 404 Not Found',
                }
                item['D:propstat'].append(not_found)

            # print(ns_map)
            # TODO ns0 => DAV:
            for k, v in ns_map.items():
                item['@xmlns:{}'.format(v)] = k

            pprint(item)
            response.append(item)

        return self._create_property_response_xml(response)

    async def do_propfind(
        self, send: Callable, request: DAVRequest, prefix: str, path: str,
        depth: int
    ) -> bytes:
        raise NotImplementedError

    def _create_proppatch_response(
        self, prefix, path, sucess_ids: list[DAVPropertyIdentity]
    ) -> bytes:
        data = dict()
        for ns, key in sucess_ids:
            # data['ns1:{}'.format(item)] = None
            data['D:{}'.format(key)] = None  # forget namespace support !!!

        # href = '{}{}'.format(prefix, path)
        response = {
            'D:href': path,
            'D:propstat': {
                'D:prop': data,
                'D:status': 'HTTP/1.1 200 OK',
            }
        }
        # from prettyprinter import pprint
        # pprint(response)
        return self._create_property_response_xml(response)

    async def do_proppatch(
        self, request: DAVRequest, passport: DistributionPassport
    ):
        http_status = await self._do_proppatch(
            passport.src_path, request.proppatch_entries
        )

        if http_status == 207:
            sucess_ids = [x[0] for x in request.proppatch_entries]
            message = self._create_proppatch_response(
                passport.src_prefix, request.src_path, sucess_ids
            )
        else:
            message = b''

        await send_response_in_one_call(
            request.send, http_status, message
        )
        return

    async def _do_proppatch(
        self, path: str, property_patches: list[DAVPropertyPatches]
    ) -> int:
        raise NotImplementedError

    async def do_mkcol(self, path: str) -> int:
        raise NotImplementedError

    async def do_get(self, path: str, send: Callable) -> int:
        raise NotImplementedError

    async def do_head(self, path: str) -> bool:
        raise NotImplementedError

    async def do_delete(self, path: str) -> int:
        raise NotImplementedError

    async def do_put(self, path: str, receive: Callable) -> int:
        raise NotImplementedError

    async def do_copy(
        self, src_path: str, dst_path: str, depth: int, overwrite: bool = False
    ) -> int:
        raise NotImplementedError

    async def do_move(
        self, src_path: str, dst_path: str, overwrite: bool = False
    ) -> int:
        raise NotImplementedError
