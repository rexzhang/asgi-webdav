from typing import Optional
from dataclasses import dataclass
from logging import getLogger

from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVPassport,
)
from asgi_webdav.config import Config
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.provider.file_system import FileSystemProvider
from asgi_webdav.provider.memory import MemoryProvider
from asgi_webdav.response import DAVResponse

logger = getLogger(__name__)


@dataclass
class ProviderMapping:
    prefix: Optional[DAVPath]
    weight: int
    provider: Optional[DAVProvider]
    readonly: bool = False  # TODO impl

    def __repr__(self):
        return 'Mapping: {} => {}'.format(self.prefix, self.provider)


class DAVDistributor:
    def __init__(self, config: Config):
        self.path_prefix_table = list()
        for mapping in config.provider_mapping:
            if mapping.uri.startswith('file://'):
                mp = ProviderMapping(
                    prefix=DAVPath(mapping.prefix),
                    weight=len(mapping.prefix),
                    provider=FileSystemProvider(root_path=mapping.uri[7:])
                )
                self.path_prefix_table.append(mp)
                logger.info(mp)

            elif mapping.uri.startswith('memory://'):
                mp = ProviderMapping(
                    prefix=DAVPath(mapping.prefix),
                    weight=len(mapping.prefix),
                    provider=MemoryProvider()
                )
                self.path_prefix_table.append(mp)
                logger.info(mp)

            else:
                raise

    async def distribute(self, request: DAVRequest):
        passport = self.get_passport(request.src_path, request.dst_path)
        if passport is None:
            raise

        # parser body
        await request.parser_body()
        logger.debug(request)

        # call method
        # high freq interface ---
        if request.method == DAVMethod.HEAD:
            response = await passport.provider.do_head(request, passport)

        elif request.method == DAVMethod.GET:
            response = await passport.provider.do_get(request, passport)

        elif request.method == DAVMethod.PROPFIND:
            response = await passport.provider.do_propfind(request, passport)

        elif request.method == DAVMethod.PROPPATCH:
            response = await passport.provider.do_proppatch(request, passport)

        elif request.method == DAVMethod.LOCK:
            response = await passport.provider.do_lock(request, passport)

        elif request.method == DAVMethod.UNLOCK:
            response = await passport.provider.do_unlock(request, passport)

        # low freq interface ---
        elif request.method == DAVMethod.MKCOL:
            response = await passport.provider.do_mkcol(request, passport)

        elif request.method == DAVMethod.DELETE:
            response = await passport.provider.do_delete(request, passport)

        elif request.method == DAVMethod.PUT:
            response = await passport.provider.do_put(request, passport)

        elif request.method == DAVMethod.COPY:
            response = await passport.provider.do_copy(request, passport)

        elif request.method == DAVMethod.MOVE:
            response = await passport.provider.do_move(request, passport)

        # other interface ---
        elif request.method == DAVMethod.OPTIONS:
            response = await passport.provider.get_options(request, passport)

        else:
            raise Exception('{} is not support method'.format(request.method))

        logger.debug(response)
        await response.send_in_one_call(request.send)
        return

    def get_passport(
        self, src_path: DAVPath, dst_path: DAVPath
    ) -> Optional[DAVPassport]:
        # match provider
        path_prefix = ProviderMapping(None, 0, None)
        for path_prefix_x in self.path_prefix_table:
            if not src_path.startswith(path_prefix_x.prefix):
                continue

            if path_prefix_x.weight > path_prefix.weight:
                path_prefix = path_prefix_x

        if path_prefix.provider is None:
            return None

        # create passport
        if dst_path:
            dst_path = dst_path.get_child(path_prefix.prefix)
        else:
            dst_path = None

        passport = DAVPassport(
            provider=path_prefix.provider,

            src_prefix=path_prefix.prefix,
            src_path=src_path.get_child(path_prefix.prefix),
            dst_path=dst_path,
        )
        return passport

    async def do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> DAVResponse:
        if not request.body_is_parsed_success:
            # TODO ??? 40x?
            return DAVResponse(400)

        properties = await self._do_propfind(request, passport)
        if properties is None:
            return DAVResponse(404)

        message = await self._create_propfind_response(
            request, passport, properties
        )
        response = DAVResponse(status=207, message=message)
        return response
