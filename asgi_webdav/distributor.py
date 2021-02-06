from pathlib import PurePath
from collections import namedtuple

from asgi_webdav.constants import (
    DAV_METHOD,
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
    def __init__(self):
        config_path_map = [
            # prefix 需要以 / 结束
            ('/', '/Users/rex/p/asgi-webdav/litmus_test/test'),
            ('/litmus/', '/Users/rex/p/asgi-webdav/litmus_test/litmus'),
            ('/joplin/', '/Users/rex/p/asgi-webdav/litmus_test/joplin'),
        ]

        self.path_map = list()
        for logic_path, real_path in config_path_map:
            prefix_path_parts = PurePath(logic_path).parts[1:]
            self.path_map.append(PathPrefix(
                logic_path, prefix_path_parts, len(prefix_path_parts),
                len(logic_path), FileSystemProvider(root_path=real_path)
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
        if request.method == DAV_METHOD.HEAD:
            await self.do_head(request, passport)

        elif request.method == DAV_METHOD.GET:
            await self.do_get(request, passport)

        # low freq interface ---
        elif request.method == DAV_METHOD.MKCOL:
            await self.do_mkcol(request, passport)

        elif request.method == DAV_METHOD.DELETE:
            await self.do_delete(request, passport)

        elif request.method == DAV_METHOD.PUT:
            await self.do_put(request, passport)

        elif request.method == DAV_METHOD.COPY:
            await self.do_copy(request, passport)

        elif request.method == DAV_METHOD.MOVE:
            await self.do_move(request, passport)

        # other interface ---
        elif request.method == DAV_METHOD.PROPFIND:
            await self.do_propfind(request, passport)

        elif request.method == DAV_METHOD.PROPPATCH:
            await self.do_proppatch(request, passport)

        elif request.method == DAV_METHOD.OPTIONS:
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
                b'GET, HEAD, POST, PUT, DELETE, OPTIONS, PROPFIND, PROPPATCH, '
                b'MKCOL, LOCK, UNLOCK, MOVE, COPY'
            ),
            (b'DAV', b'1, 2'),
        ]
        await send_response_in_one_call(request.send, 200, headers=headers)
