from typing import Optional
from dataclasses import dataclass
from logging import getLogger

from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVDepth,
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
class PrefixProviderMapping:
    prefix: Optional[DAVPath]
    weight: int
    provider: Optional[DAVProvider]
    readonly: bool = False  # TODO impl

    def __repr__(self):
        return 'Mapping: {} => {}'.format(self.prefix, self.provider)


class DAVDistributor:
    def __init__(self, config: Config):
        self.prefix_provider_mapping = list()
        for pm in config.provider_mapping:
            if pm.uri.startswith('file://'):
                provider = FileSystemProvider(
                    prefix=DAVPath(pm.prefix),
                    root_path=pm.uri[7:]
                )

            elif pm.uri.startswith('memory://'):
                provider = MemoryProvider(prefix=DAVPath(pm.prefix))

            else:
                raise

            ppm = PrefixProviderMapping(
                prefix=DAVPath(pm.prefix),
                weight=len(pm.prefix),
                provider=provider
            )
            self.prefix_provider_mapping.append(ppm)
            logger.info(ppm)

        self.prefix_provider_mapping.sort(
            key=lambda x: getattr(x, 'weight'), reverse=True
        )

    # def match_prefix(self, path: DAVPath) -> list[PrefixProviderMapping]:
    #     result = list()
    #     for ppm in self.prefix_provider_mapping:
    #         if path.startswith(ppm.prefix):
    #             result.append(ppm)
    #
    #     return result

    def get_passport(
        self, src_path: DAVPath, dst_path: DAVPath
    ) -> Optional[DAVPassport]:
        prefix = None
        weight = None
        provider = None

        # match provider
        for ppm in self.prefix_provider_mapping:
            if not src_path.startswith(ppm.prefix):
                continue

            if weight is None:  # or ppm.weight < weight:
                prefix = ppm.prefix
                weight = ppm.weight
                provider = ppm.provider
                break  # self.prefix_provider_mapping is sorted!

        # create passport
        if weight is None:
            return None

        if dst_path:
            dst_path = dst_path.get_child(prefix)
        else:
            dst_path = None

        return DAVPassport(
            provider=provider,

            src_prefix=prefix,
            src_path=src_path.get_child(prefix),
            dst_path=dst_path,
        )

    def get_depth_1_child_provider(self, prefix: DAVPath) -> list[DAVProvider]:
        l = list()
        for ppm in self.prefix_provider_mapping:
            if ppm.prefix.startswith(prefix):
                if ppm.prefix.get_child(prefix).count == 1:
                    # l.append(ppm.prefix.name)
                    l.append(ppm.provider)

        return l

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
            response = await self.do_propfind(request, passport)

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

    async def do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> DAVResponse:
        if not request.body_is_parsed_success:
            # TODO ??? 40x?
            return DAVResponse(400)

        dav_properties = await passport.provider.do_propfind(request, passport)
        if len(dav_properties) == 0:
            return DAVResponse(404)

        if request.depth != DAVDepth.d0:
            for provider in self.get_depth_1_child_provider(
                passport.src_prefix
            ):
                # TODO!!!
                dav_properties[
                    provider.dav_property.href_path
                ] = provider.dav_property

        message = await passport.provider.create_propfind_response(
            request, dav_properties
        )
        response = DAVResponse(status=207, message=message)
        return response
