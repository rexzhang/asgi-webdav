from pathlib import PurePath
from collections import namedtuple

from asgi_webdav.constants import (
    DAVMethod,
    DAV_METHODS,
    DAVDistributeMap,
    DAVPassport,
)
from asgi_webdav.helpers import send_response_in_one_call
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.file_system import FileSystemProvider

PathPrefix = namedtuple(
    'PathPrefix',
    (
        'path', 'path_parts', 'path_parts_number',
        'weight',  # biggest == highest
        'provider'
    )
)


class DAVDistributor:
    def __init__(self, dist_map: DAVDistributeMap):

        self.path_map = list()
        for prefix, real_path in dist_map.items():
            prefix_path_parts = PurePath(prefix).parts[1:]
            self.path_map.append(PathPrefix(
                prefix, prefix_path_parts, len(prefix_path_parts),
                len(prefix), FileSystemProvider(root_path=real_path)
            ))

    async def distribute(self, request: DAVRequest):
        prefix = None
        provider = None
        weight = None
        for path_prefix in self.path_map:
            if not request.src_path.startswith(path_prefix.path.rstrip('/')):
                continue

            new_weight = path_prefix.weight
            if weight is None or new_weight > weight:
                prefix = path_prefix.path
                provider = path_prefix.provider
                weight = new_weight

        if provider is None:
            raise

        if request.dst_path:
            dst_path = request.dst_path[weight:]
        else:
            dst_path = None
        passport = DAVPassport(
            provider=provider,

            src_prefix=prefix,
            src_path=request.src_path[weight:],
            dst_path=dst_path,
        )
        # high freq interface ---
        if request.method == DAVMethod.HEAD:
            await self.do_head(request, passport)

        elif request.method == DAVMethod.GET:
            await self.do_get(request, passport)

        # low freq interface ---
        elif request.method == DAVMethod.MKCOL:
            await self.do_mkcol(request, passport)

        elif request.method == DAVMethod.DELETE:
            await self.do_delete(request, passport)

        elif request.method == DAVMethod.PUT:
            await self.do_put(request, passport)

        elif request.method == DAVMethod.COPY:
            await self.do_copy(request, passport)

        elif request.method == DAVMethod.MOVE:
            await self.do_move(request, passport)

        # other interface ---
        elif request.method == DAVMethod.PROPFIND:
            await self.do_propfind(request, passport)

        elif request.method == DAVMethod.PROPPATCH:
            await self.do_proppatch(request, passport)

        elif request.method == DAVMethod.OPTIONS:
            await self.get_options(request, passport)

        else:
            raise

        return

    async def do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_propfind(request, passport)
        return

    async def do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_proppatch(request, passport)
        return

    async def do_mkcol(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_mkcol(request, passport)
        return

    async def do_get(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_get(request, passport)
        return

    async def do_head(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_head(request, passport)
        return

    async def do_delete(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_delete(request, passport)
        return

    async def do_put(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_put(request, passport)
        return

    async def do_copy(
        self, request: DAVRequest, passport: DAVPassport
    ):

        await passport.provider.do_copy(request, passport)
        return

    async def do_move(
        self, request: DAVRequest, passport: DAVPassport
    ):

        await passport.provider.do_move(request, passport)
        return

    async def get_options(
        self, request: DAVRequest, passport: DAVPassport
    ):  # TODO!!!
        headers = [
            (
                b'Allow',
                bytes(','.join(DAV_METHODS), encoding='utf-8')
            ),
            (b'DAV', b'1, 2'),
        ]
        await send_response_in_one_call(request.send, 200, headers=headers)
