from typing import Optional
import asyncio
from uuid import UUID, uuid4
from time import time

from asgi_webdav.constants import (
    DAVPath,
    DAVLockScope,  # TODO!!!
    DAVLockInfo
)
from asgi_webdav.request import DAVRequest


class DAVLock:
    def __init__(self):
        self.lock = asyncio.Lock()

        # path is request.src_path or request_dst_path
        #   or request.xxx_path + child
        self.path2token_map: dict[DAVPath, set[UUID]] = dict()
        self.lock_map: dict[UUID, DAVLockInfo] = dict()

    def _create_new_lock(self, request: DAVRequest) -> DAVLockInfo:
        info = DAVLockInfo(
            path=request.src_path,
            depth=request.depth,
            timeout=request.timeout,  # TODO !!!
            scope=request.lock_scope,
            owner=request.lock_owner,
            token=uuid4()
        )

        if request.src_path not in self.path2token_map:
            self.path2token_map[info.path] = set()
        self.path2token_map[info.path].add(info.token)

        self.lock_map[info.token] = info
        return info

    # TODO no DAVRequest
    async def new(self, request: DAVRequest) -> Optional[DAVLockInfo]:
        """return None if create lock failed"""
        async with self.lock:
            if request.src_path not in self.path2token_map:
                info = self._create_new_lock(request)
                return info

            if request.lock_scope == DAVLockScope.exclusive:
                return None

            # TODO support DAVLockScope.shared !!!
            return None

    async def refresh(self, token: UUID) -> Optional[DAVLockInfo]:
        async with self.lock:
            info = self.lock_map.get(token)
            if info:
                info.update_expire()
                self.lock_map[token] = info
                return info

        return None

    def _get_lock_info(
        self, token: UUID, timestamp: float = None
    ) -> Optional[DAVLockInfo]:
        info = self.lock_map.get(token)
        if info is None:
            return None

        if timestamp is None:
            timestamp = time()

        if info.expire > timestamp:
            return info

        self._remove_token(token, info.path)
        return None

    async def is_locking(
        self, path: DAVPath, owner_token: UUID = None
    ) -> bool:
        # print('LOCK_INFO:{}, {}'.format(path, self.path2token_map.keys()))
        async with self.lock:
            token_set = self.path2token_map.get(path)
            if not isinstance(token_set, set):  # token_set is None
                return False

            timestamp = time()
            for token in list(token_set):
                if token == owner_token:
                    return False

                info = self._get_lock_info(token, timestamp)
                if info:
                    return True

        return False

    async def get_info_by_path(self, path: DAVPath) -> list[DAVLockInfo]:
        result = list()
        async with self.lock:
            if path in self.path2token_map:
                for token in self.path2token_map[path]:
                    info = self._get_lock_info(token)
                    if info:
                        result.append(info)

        return result

    async def get_info_by_token(self, token: UUID) -> Optional[DAVLockInfo]:
        async with self.lock:
            info = self._get_lock_info(token)
            if info:
                return info

        return None

    def _remove_token(self, token: UUID, path: DAVPath):
        self.lock_map.pop(token)

        self.path2token_map[path].remove(token)
        if len(self.path2token_map[path]) == 0:
            self.path2token_map.pop(path)

        return

    async def release(self, token: UUID) -> bool:
        async with self.lock:
            info = self.lock_map.get(token, None)
            if info is None:
                return False

            # if info.path in self.path2token_map:
            self._remove_token(token, info.path)

        return True

    async def _release_by_path(self, path: DAVPath):
        """test only"""
        async with self.lock:
            for token in list(self.path2token_map[path]):
                self._remove_token(token, path)

    def __repr__(self):
        try:
            from prettyprinter import pformat
            s = '{}\n{}'.format(
                pformat(self.path2token_map), pformat(self.lock_map)
            )
        except ImportError:
            s = '{}\n{}'.format(
                ','.join(self.path2token_map.keys().__str__()),
                ','.join(self.lock_map.keys().__str__())
            )

        return s
