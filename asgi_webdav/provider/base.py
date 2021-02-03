from typing import Optional, Callable

import xmltodict

from asgi_webdav.constants import (
    DAVRequest,
    DistributionPassport,
    DAVProperty,
)
from asgi_webdav.helpers import (
    DateTime,
    send_response_in_one_call,
)


class DAVProvider:
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
        for properties in properties_list:
            href = '{}{}'.format(prefix, properties.path)

            if properties.resource_type_is_dir:
                resource_type = {'D:collection': None}
            else:
                resource_type = None

            item = {
                'D:href': href,
                'D:propstat': {
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

                        'D:supportedlock': {
                            'D:lockentry': [
                                {
                                    'D:lockscope': {'D:exclusive': ''},
                                    'D:locktype': {'D:write': ''}
                                },
                                {
                                    'D:lockscope': {'D:shared': None},
                                    'D:locktype': {'D:write': None}
                                }
                            ]
                        },
                        'D:lockdiscovery': None,
                    },
                    'D:status': 'HTTP/1.1 200 OK',
                }
            }
            response.append(item)

        return self._create_property_response_xml(response)

    async def do_propfind(
        self, send: Callable, prefix: str, path: str, depth: int
    ) -> bytes:
        raise NotImplementedError

    def _create_proppatch_response(self, prefix, path, properties) -> bytes:
        data = dict()
        for item in properties.keys():
            # data['ns1:{}'.format(item)] = None
            data['D:{}'.format(item)] = None  # forget namespace support !!!

        # href = '{}{}'.format(prefix, path)
        response = {
            'D:href': path,
            'D:propstat': {
                'D:prop': data,
                'D:status': 'HTTP/1.1 200 OK',
            }
        }
        from prettyprinter import pprint
        pprint(response)
        return self._create_property_response_xml(response)

    async def do_proppatch(
        self, request: DAVRequest, passport: DistributionPassport
    ):
        http_status = await self._do_proppatch(
            passport.src_path, request.properties
        )

        if http_status == 207:
            message = self._create_proppatch_response(
                passport.src_prefix, request.src_path, request.properties
            )
        else:
            message = b''

        await send_response_in_one_call(
            request.send, http_status, message
        )
        return

    async def _do_proppatch(self, path: str, properties: dict[str]) -> int:
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
