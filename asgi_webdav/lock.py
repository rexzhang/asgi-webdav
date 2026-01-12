from __future__ import annotations

import asyncio
from time import time
from uuid import UUID, uuid4

from asgi_webdav.constants import (
    DAVDepth,
    DAVLockObj,
    DAVLockObjSet,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
    DAVPath,
)
from asgi_webdav.exceptions import DAVCodingError


class DAVLockKeeper:
    _asyncio_lock: asyncio.Lock

    # path:
    # - src_path/dst_path
    # - provider_prefix + dist_src_path/dist_dst_path
    # _path2tokens: dict[DAVPath, DAVLockTokens]
    _token2lock_obj: dict[UUID, DAVLockObj]
    _path2lock_obj_set: dict[DAVPath, DAVLockObjSet]

    def __init__(self) -> None:
        self._asyncio_lock = asyncio.Lock()

        self._token2lock_obj = dict()
        self._path2lock_obj_set = dict()

    async def get(self, token: UUID) -> DAVLockObj | None:
        """get lock obj by token, return None if not found or expired"""
        async with self._asyncio_lock:
            lock_obj = self._token2lock_obj.get(token)
            if lock_obj is None:
                return None

            if lock_obj.is_expired():
                self._release(lock_obj)
                return None

            return lock_obj

    async def new(
        self,
        owner: str,
        path: DAVPath,
        depth: DAVDepth = DAVDepth.infinity,
        scope: DAVLockScope = DAVLockScope.exclusive,
        timeout: int = DAVLockTimeoutMaxValue,
    ) -> DAVLockObj | None:
        """return None if create lock failed"""
        async with self._asyncio_lock:
            lock_obj = DAVLockObj(
                owner=owner,
                path=path,
                depth=depth,
                token=uuid4(),
                scope=scope,
                timeout=timeout,
            )
            success = self._new_path2lock_obj_set(path, scope, lock_obj)
            if not success:
                return None

            self._token2lock_obj[lock_obj.token] = lock_obj
            return lock_obj

    def _new_path2lock_obj_set(
        self, path: DAVPath, lock_scope: DAVLockScope, lock_obj: DAVLockObj
    ) -> bool:
        lock_obj_set = self._path2lock_obj_set.get(path)
        if lock_obj_set is None:
            # new lock for path
            self._path2lock_obj_set[path] = DAVLockObjSet(lock_scope, {lock_obj})
            return True

        if lock_scope == DAVLockScope.exclusive:
            return False

        if lock_obj_set.lock_scope == DAVLockScope.exclusive:
            return False

        lock_obj_set.add(lock_obj)
        return True

    async def refresh(
        self, lock_obj: DAVLockObj, timeout: int | None = None
    ) -> DAVLockObj:
        """
        because lock_obj is already checked by caller:
        - skip path check
        - skip expire check
        """
        async with self._asyncio_lock:
            if timeout is not None and 0 < timeout <= DAVLockTimeoutMaxValue:
                lock_obj.timeout = timeout

            lock_obj.update_expire()
            return lock_obj

    async def release(self, token: UUID) -> bool:
        async with self._asyncio_lock:
            lock_obj = self._token2lock_obj.get(token)
            if lock_obj is None:
                return False

            return self._release(lock_obj)

    def _release(self, lock_obj: DAVLockObj) -> bool:
        success = self._release_path2lock_set(lock_obj)
        if not success:
            return False

        self._token2lock_obj.pop(lock_obj.token)
        return True

    def _release_path2lock_set(self, lock_obj: DAVLockObj) -> bool:
        path = lock_obj.path

        if path not in self._path2lock_obj_set:
            return False

        lock_obj_set = self._path2lock_obj_set[path]
        if lock_obj not in lock_obj_set:
            return False

        lock_obj_set.remove(lock_obj)
        if lock_obj_set.is_empty():
            self._path2lock_obj_set.pop(path)

        return True

    async def is_valid_lock_token(self, token: UUID, path: DAVPath) -> bool:
        async with self._asyncio_lock:
            lock_obj = self._token2lock_obj.get(token)
            if lock_obj is None:
                return False

            if not lock_obj.check_path(path):
                return False

            if lock_obj.is_expired():
                if not self._release(lock_obj):
                    raise DAVCodingError

                return False

            return True

    async def get_lock_objs_from_path(self, path: DAVPath) -> list[DAVLockObj]:
        now = time()

        lock_obj_expired = set()
        result: list[DAVLockObj] = list()
        async with self._asyncio_lock:
            for lock_path, lock_obj_set in self._path2lock_obj_set.items():
                if not lock_path.is_parent_of_or_is_self(path):
                    continue

                for lock_obj in lock_obj_set.data:
                    if lock_obj.is_expired(now=now):
                        lock_obj_expired.add(lock_obj)
                        continue

                    if not lock_obj.check_path(path):
                        continue

                    result.append(lock_obj)

            for lock_obj in lock_obj_expired:
                if not self._release(lock_obj):
                    raise DAVCodingError

        return result

    async def has_lock(self, path: DAVPath) -> bool:
        """res path is locking by any lock"""
        return len(await self.get_lock_objs_from_path(path)) > 0
