from typing import Optional
from dataclasses import dataclass
from logging import getLogger

from prettyprinter import pprint

from asgi_webdav.constants import (
    DAVMethod,
    DAV_METHODS,
    DAVPath,
    DAVPassport,
    DAVResponse,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.provider.file_system import FileSystemProvider

logger = getLogger(__name__)


@dataclass
class PathPrefix:
    path: Optional[DAVPath]
    weight: int
    provider: any  # TODO


class DAVDistributor:
    def __init__(self, dist_map: dict[str, str]):
        self.path_prefix_table = list()
        for prefix, root_path in dist_map.items():
            # logging.info('Mapping: {} => {}'.format(prefix, root_path))
            logger.info('Mapping: {} => {}'.format(prefix, root_path))
            self.path_prefix_table.append(PathPrefix(
                path=DAVPath(prefix),
                weight=len(prefix),
                provider=FileSystemProvider(root_path=root_path)
            ))

    async def distribute(self, request: DAVRequest):
        path_prefix = PathPrefix(None, 0, None)
        for path_prefix_x in self.path_prefix_table:
            if not request.src_path.startswith(path_prefix_x.path):
                continue

            if path_prefix_x.weight > path_prefix.weight:
                path_prefix = path_prefix_x

        if path_prefix.provider is None:
            raise  # TODO!!!

        if request.dst_path:
            dst_path = request.dst_path.child(path_prefix.path)
        else:
            dst_path = None

        passport = DAVPassport(
            provider=path_prefix.provider,

            src_prefix=path_prefix.path,
            src_path=request.src_path.child(path_prefix.path),
            dst_path=dst_path,
        )
        # high freq interface ---
        if request.method == DAVMethod.HEAD:
            await self.do_head(request, passport)

        elif request.method == DAVMethod.GET:
            await self.do_get(request, passport)

        elif request.method == DAVMethod.LOCK:
            await self.do_lock(request, passport)

        elif request.method == DAVMethod.UNLOCK:
            await self.do_unlock(request, passport)

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

    async def do_lock(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_lock(request, passport)
        return

    async def do_unlock(
        self, request: DAVRequest, passport: DAVPassport
    ):
        await passport.provider.do_unlock(request, passport)
        return

    async def get_options(
        self, request: DAVRequest, passport: DAVPassport
    ):  # TODO

        response = DAVResponse(status=200, headers=[
            (
                b'Allow',
                bytes(','.join(DAV_METHODS), encoding='utf-8')
            ),
            (b'DAV', b'1, 2'),
        ])
        await response.send_in_one_call(request.send)
