from typing import Optional
from dataclasses import dataclass
from logging import getLogger

from asgi_webdav.constants import (
    DAVMethod,
    DAVPath,
    DAVPassport,
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
            logger.info('Mapping: {} => {}'.format(prefix, root_path))
            self.path_prefix_table.append(PathPrefix(
                path=DAVPath(prefix),
                weight=len(prefix),
                provider=FileSystemProvider(root_path=root_path)
            ))

    async def distribute(self, request: DAVRequest):
        # match provider
        path_prefix = PathPrefix(None, 0, None)
        for path_prefix_x in self.path_prefix_table:
            if not request.src_path.startswith(path_prefix_x.path):
                continue

            if path_prefix_x.weight > path_prefix.weight:
                path_prefix = path_prefix_x

        if path_prefix.provider is None:
            raise  # TODO!!!

        # create passport
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
