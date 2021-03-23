from typing import Optional
from dataclasses import dataclass
from copy import copy
from logging import getLogger

from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVDepth,
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
    prefix: DAVPath
    weight: int
    provider: DAVProvider
    readonly: bool = False  # TODO impl

    def __repr__(self):
        return 'Mapping: {} => {}'.format(self.prefix, self.provider)


class DAVDistributor:
    def __init__(self, config: Config):
        self.prefix_provider_mapping = list()
        for pm in config.provider_mapping:
            if pm.uri.startswith('file://'):
                provider = FileSystemProvider(
                    dist_prefix=DAVPath(pm.prefix),
                    root_path=pm.uri[7:]
                )

            elif pm.uri.startswith('memory://'):
                provider = MemoryProvider(
                    dist_prefix=DAVPath(pm.prefix)
                )

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

    def match_provider(self, request: DAVRequest) -> Optional[DAVProvider]:
        weight = None
        provider = None

        # match provider
        for ppm in self.prefix_provider_mapping:
            if not request.src_path.startswith(ppm.prefix):
                continue

            if weight is None:  # or ppm.weight < weight:
                weight = ppm.weight
                provider = ppm.provider
                break  # self.prefix_provider_mapping is sorted!

        if weight is None:
            return None

        return provider

    async def distribute(self, request: DAVRequest):
        provider = self.match_provider(request)
        if provider is None:
            raise

        # update request distribute information
        request.update_distribute_info(provider.dist_prefix)

        # parser body
        await request.parser_body()
        logger.debug(request)

        # call method
        # high freq interface ---
        if request.method == DAVMethod.HEAD:
            response = await provider.do_head(request)

        elif request.method == DAVMethod.GET:
            response = await provider.do_get(request)

        elif request.method == DAVMethod.PROPFIND:
            response = await self.do_propfind(request, provider)

        elif request.method == DAVMethod.PROPPATCH:
            response = await provider.do_proppatch(request)

        elif request.method == DAVMethod.LOCK:
            response = await provider.do_lock(request)

        elif request.method == DAVMethod.UNLOCK:
            response = await provider.do_unlock(request)

        # low freq interface ---
        elif request.method == DAVMethod.MKCOL:
            response = await provider.do_mkcol(request)

        elif request.method == DAVMethod.DELETE:
            response = await provider.do_delete(request)

        elif request.method == DAVMethod.PUT:
            response = await provider.do_put(request)

        elif request.method == DAVMethod.COPY:
            response = await provider.do_copy(request)

        elif request.method == DAVMethod.MOVE:
            response = await provider.do_move(request)

        # other interface ---
        elif request.method == DAVMethod.OPTIONS:
            response = await provider.get_options(request)

        else:
            raise Exception('{} is not support method'.format(request.method))

        logger.debug(response)
        await response.send_in_one_call(request.send)
        return

    def get_depth_1_child_provider(self, prefix: DAVPath) -> list[DAVProvider]:
        providers = list()
        for ppm in self.prefix_provider_mapping:
            if ppm.prefix.startswith(prefix):
                if ppm.prefix.get_child(prefix).count == 1:
                    providers.append(ppm.provider)

        return providers

    async def do_propfind(
        self, request: DAVRequest, provider: DAVProvider
    ) -> DAVResponse:
        if not request.body_is_parsed_success:
            # TODO ??? 40x?
            return DAVResponse(400)

        dav_properties = await provider.do_propfind(request)
        if len(dav_properties) == 0:
            return DAVResponse(404)

        if request.depth != DAVDepth.d0:
            for child_provider in self.get_depth_1_child_provider(
                request.src_path
            ):
                child_request = copy(request)
                if request.depth == DAVDepth.d1:
                    child_request.depth = DAVDepth.d0
                elif request.depth == DAVDepth.infinity:
                    child_request.depth = DAVDepth.d1  # TODO support infinity

                child_request.src_path = child_provider.dist_prefix
                child_request.update_distribute_info(
                    child_provider.dist_prefix
                )
                child_dav_properties = await child_provider.do_propfind(
                    child_request
                )
                dav_properties.update(child_dav_properties)

        message = await provider.create_propfind_response(
            request, dav_properties
        )
        response = DAVResponse(status=207, message=message)
        return response
