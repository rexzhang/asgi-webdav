from typing import Optional, Callable

import xmltodict

from asgi_webdav.constants import DAVProperty
from asgi_webdav.helpers import DateTime


class DAVProvider:
    @staticmethod
    def _create_propfind_xml(props: list[DAVProperty], prefix: str) -> bytes:
        responses = list()
        for prop in props:
            href = '{}{}'.format(prefix, prop.path)

            if prop.resource_type_is_dir:
                resource_type = {'D:collection': None}
            else:
                resource_type = None

            response = {
                'D:href': href,
                'D:propstat': {
                    'D:prop': {
                        'D:getcontenttype': prop.content_type,
                        'D:displayname': prop.display_name,
                        'D:creationdate': DateTime(
                            prop.creation_date
                        ).iso_8601(),
                        'D:getetag': prop.etag,
                        'D:getlastmodified': DateTime(
                            prop.last_modified
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
            responses.append(response)

        data = {
            'D:multistatus': {
                '@xmlns:D': 'DAV:',
                'D:response': responses,
            }
        }
        return bytes(
            # TODO xmltodict have bug:
            #   '\n'
            #   <D:resourcetype>
            #       <D:collection></D:collection>
            #   </D:resourcetype>
            #   <D:resourcetype>
            #       <D:collection/>
            #   </D:resourcetype>
            xmltodict.unparse(data).replace('\n', ''), encoding='utf-8'
        )

    async def do_propfind(
        self, send: Callable, prefix: str, path: str, depth: int
    ) -> bytes:
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
