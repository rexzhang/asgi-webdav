import asyncio
import pprint
from time import time
from uuid import UUID, uuid4

from asgi_webdav.constants import DAVLockInfo, DAVLockScope, DAVPath
from asgi_webdav.request import DAVRequest


class Path2TokenMap:
    """
    path is request.src_path or request_dst_path
        or request.xxx_path + child
    """

    data: dict[DAVPath, tuple[DAVLockScope, set[UUID]]]

    def __init__(self):
        self.data = dict()

    def __contains__(self, item: DAVPath):
        return item in self.data

    def keys(self):
        return self.data.keys()

    def get_tokens(self, path: DAVPath) -> list[UUID]:
        tokens = list()
        for locked_path in self.data.keys():
            if not path.startswith(locked_path):
                continue

            tokens += list(self.data.get(locked_path)[1])

        return tokens

    def add(self, path: DAVPath, lock_scope: DAVLockScope, token: UUID) -> bool:
        if path not in self.data:
            self.data[path] = (lock_scope, {token})
            return True

        if lock_scope == DAVLockScope.exclusive:
            return False

        self.data[path][1].add(token)
        return True

    def remove(self, path: DAVPath, token: UUID) -> bool:
        if path not in self.data:
            return False

        self.data[path][1].remove(token)
        if len(self.data[path][1]) == 0:
            self.data.pop(path)

        return True


class DAVLock:
    def __init__(self):
        self.lock = asyncio.Lock()

        self.path2token_map = Path2TokenMap()
        self.lock_map: dict[UUID, DAVLockInfo] = dict()

    async def new(self, request: DAVRequest) -> DAVLockInfo | None:
        """return None if create lock failed"""
        async with self.lock:
            # TODO no DAVRequest
            info = DAVLockInfo(
                path=request.src_path,
                depth=request.depth,
                timeout=request.timeout,
                lock_scope=request.lock_scope,
                owner=request.lock_owner,
                token=uuid4(),
            )
            success = self.path2token_map.add(
                request.src_path, request.lock_scope, info.token
            )
            if not success:
                return None
            self.lock_map[info.token] = info

            return info

    async def refresh(self, token: UUID) -> DAVLockInfo | None:
        async with self.lock:
            info = self.lock_map.get(token)
            if info:
                info.update_expire()
                self.lock_map[token] = info
                return info

        return None

    def _get_lock_info(
        self, token: UUID, timestamp: float = None
    ) -> DAVLockInfo | None:
        info = self.lock_map.get(token)
        if info is None:
            return None

        if timestamp is None:
            timestamp = time()

        if info.expire > timestamp:
            return info

        self._remove_token(info.path, token)
        return None

    async def is_locking(self, path: DAVPath, owner_token: UUID = None) -> bool:
        async with self.lock:
            timestamp = time()
            for token in self.path2token_map.get_tokens(path):
                if token == owner_token:
                    return False

                info = self._get_lock_info(token, timestamp)
                if info:
                    return True

        return False

    async def get_info_by_path(self, path: DAVPath) -> list[DAVLockInfo]:
        result = list()
        async with self.lock:
            if path not in self.path2token_map:
                return result

            for token in self.path2token_map.get_tokens(path):
                info = self._get_lock_info(token)
                if info:
                    result.append(info)

        return result

    async def get_info_by_token(self, token: UUID) -> DAVLockInfo | None:
        async with self.lock:
            info = self._get_lock_info(token)
            if info:
                return info

        return None

    def _remove_token(self, path: DAVPath, token: UUID):
        self.path2token_map.remove(path, token)
        self.lock_map.pop(token)
        return

    async def release(self, token: UUID) -> bool:
        async with self.lock:
            info = self.lock_map.get(token, None)
            if info is None:
                return False

            self._remove_token(info.path, token)

        return True

    async def _release_by_path(self, path: DAVPath):
        """test only"""
        async with self.lock:
            for token in self.path2token_map.get_tokens(path):
                self._remove_token(path, token)

    def __repr__(self):
        s = "{}\n{}".format(
            pprint.pformat(self.path2token_map), pprint.pformat(self.lock_map)
        )
        return s
