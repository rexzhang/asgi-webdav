from typing import Optional
import asyncio
from uuid import UUID, uuid4
from time import time

from prettyprinter import pprint

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

    async def get_lock_by_path(
        self, path: DAVPath, request: Optional[DAVRequest] = None
    ) -> Optional[DAVLockInfo]:
        async with self.lock:
            if path in self.path2token_map:
                count = 0
                for token in self.path2token_map[path]:
                    # TODO!!!! multi-token
                    info = self.lock_map.get(token)
                    count += 1

                if count > 1:
                    raise Exception('count > 1 !!!!!')
                return info

            if request:
                return self._create_new_lock(request)

        return None

    async def get_lock_by_token(
        self, token: UUID, request: Optional[DAVRequest] = None
    ) -> Optional[DAVLockInfo]:
        async with self.lock:
            info = self.lock_map.get(token)
            if info:
                return info

            if request:
                return self._create_new_lock(request)

        return None

    async def refresh_lock(self, token: UUID) -> Optional[DAVLockInfo]:
        async with self.lock:
            info = self.lock_map.get(token)
            if info:
                info.update_expire()
                self.lock_map[token] = info
                return info

        return None

    def _remove_token(self, token: UUID, path: DAVPath):
        print('remove_token:', token, path)
        print('remove_token:', self.path2token_map.keys())
        print('remove_token:', self.path2token_map[path])
        self.path2token_map[path].remove(token)
        if len(self.path2token_map[path]) == 0:
            self.path2token_map.pop(path)

        self.lock_map.pop(token)

    async def release_lock(self, token: UUID) -> bool:
        async with self.lock:
            info = self.lock_map.get(token, None)
            if info is None:
                return False

            # if info.path in self.path2token_map:
            self._remove_token(token, info.path)

        return True

    async def release_lock_by_path(self, path: DAVPath):
        async with self.lock:
            token_set = self.path2token_map.get(path, set())
            for token in token_set:
                self._remove_token(token, path)

    async def is_locking(
        self, path: DAVPath, owner_token: UUID = None
    ) -> bool:
        print('LOCK_INFO:{}, {}'.format(path, self.path2token_map.keys()))
        async with self.lock:
            token_set = self.path2token_map.get(path)
            if token_set is None:
                return False

            is_locking = False
            for token in token_set:
                if owner_token == token:
                    continue

                info = self.lock_map.get(token)
                if info.expire > time():
                    is_locking = True
                else:
                    self._remove_token(token, path)

        return is_locking
