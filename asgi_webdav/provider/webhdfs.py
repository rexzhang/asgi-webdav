from collections.abc import AsyncGenerator
from logging import getLogger

from asgi_webdav.constants import (
    DAVPath,
)
from asgi_webdav.property import DAVProperty, DAVPropertyBasicData
from asgi_webdav.provider.dev_provider import DAVProvider
from asgi_webdav.request import DAVRequest

logger = getLogger(__name__)


class WebHDFSProvider(DAVProvider):
    def __repr__(self):
        raise NotImplementedError

    async def _do_propfind(self, request: DAVRequest) -> dict[DAVPath, DAVProperty]:
        raise NotImplementedError

    async def _do_proppatch(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_mkcol(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_get(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None, AsyncGenerator | None]:
        # 404, None, None
        # 200, DAVPropertyBasicData, None  # is_dir
        # 200/206, DAVPropertyBasicData, AsyncGenerator  # is_file
        #
        # self._create_get_head_response_headers()
        raise NotImplementedError

    async def _do_head(
        self, request: DAVRequest
    ) -> tuple[int, DAVPropertyBasicData | None]:
        raise NotImplementedError

    async def _do_delete(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_put(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_get_etag(self, request: DAVRequest) -> str:
        raise NotImplementedError

    async def _do_copy(self, request: DAVRequest) -> int:
        raise NotImplementedError

    async def _do_move(self, request: DAVRequest) -> int:
        raise NotImplementedError
