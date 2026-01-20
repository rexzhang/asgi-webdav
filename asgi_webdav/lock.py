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
        depth: DAVDepth = DAVDepth.INFINITY,
        scope: DAVLockScope = DAVLockScope.EXCLUSIVE,
        timeout: int = DAVLockTimeoutMaxValue,
        lock_objs_of_path: list[DAVLockObj] | None = None,
    ) -> DAVLockObj | None:
        """return None if create lock failed"""
        async with self._asyncio_lock:
            new_lock_obj = DAVLockObj(
                owner=owner,
                path=path,
                depth=depth,
                token=uuid4(),
                scope=scope,
                timeout=timeout,
            )
            success = self._new(new_lock_obj, lock_objs_of_path)
            if not success:
                return None

            return new_lock_obj

    def _new(
        self,
        new_lock_obj: DAVLockObj,
        lock_objs_of_path: list[DAVLockObj] | None = None,
    ) -> bool:
        """
        - 资源无锁
            - next
        - 资源有锁
            - 新锁的 scope 为 DAVLockScope.EXCLUSIVE
                - 锁定失败
            - 新锁的 scope 为 DAVLockScope.SHARED
                - 任意锁的 scope 为 DAVLockScope.EXCLUSIVE
                    - 锁定失败
                - 所有锁的 scope 为 DAVLockScope.SHARED
                    - next

        - 新锁的 depth 为 DAVDepth.ZERO
            - Success
        - 新锁的 depth 为 DAVDepth.INFINITY
            - next

        - 资源子目录无锁
            - Success
        - 资源子目录有锁
            - 新锁的 scope 为 DAVLockScope.EXCLUSIVE
                - Failed
            - 新锁的 scope 为 DAVLockScope.SHARED
                - 任意子目录锁的 scope 为 DAVLockScope.EXCLUSIVE
                    - Failed
                - 所有子目录锁的 scope 为 DAVLockScope.SHARED
                    - Success

        resource has any lock:
        - resource's path has any lock
        - path's parent path's has  any lock AND lock is DAVDepth.INFINITY
        """
        if lock_objs_of_path is None:
            lock_objs_of_path = self._get_lock_objs_from_path(new_lock_obj.path)

        if len(lock_objs_of_path) > 0:
            if new_lock_obj.scope == DAVLockScope.EXCLUSIVE:
                return False

            for lock_obj in lock_objs_of_path:
                if lock_obj.scope == DAVLockScope.EXCLUSIVE:
                    return False

        if new_lock_obj.depth == DAVDepth.ZERO:
            self._new_just_do_it(new_lock_obj)
            return True

        lock_objs_of_child_path = self._get_lock_objs_of_child_path_from_path(
            new_lock_obj.path
        )
        if len(lock_objs_of_child_path) == 0:
            self._new_just_do_it(new_lock_obj)
            return True

        if new_lock_obj.scope == DAVLockScope.EXCLUSIVE:
            return False

        for lock_obj in lock_objs_of_child_path:
            if lock_obj.scope == DAVLockScope.EXCLUSIVE:
                return False

        self._new_just_do_it(new_lock_obj)
        return True

    def _new_just_do_it(self, new_lock_obj: DAVLockObj) -> None:
        lock_obj_set = self._path2lock_obj_set.get(new_lock_obj.path)
        if lock_obj_set is None:
            self._path2lock_obj_set[new_lock_obj.path] = DAVLockObjSet(
                new_lock_obj.scope, {new_lock_obj}
            )
            self._token2lock_obj[new_lock_obj.token] = new_lock_obj
            return

        lock_obj_set.add(new_lock_obj)
        self._token2lock_obj[new_lock_obj.token] = new_lock_obj
        return

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
        path = lock_obj.path

        if path not in self._path2lock_obj_set:
            return False

        lock_obj_set = self._path2lock_obj_set[path]
        if lock_obj not in lock_obj_set:
            return False

        lock_obj_set.remove(lock_obj)
        if lock_obj_set.is_empty():
            self._path2lock_obj_set.pop(path)

        self._token2lock_obj.pop(lock_obj.token)
        return True

    async def is_valid_lock_token(self, token: UUID, path: DAVPath) -> bool:
        async with self._asyncio_lock:
            lock_obj = self._token2lock_obj.get(token)
            if lock_obj is None:
                return False

            if not lock_obj.is_locking_path(path):
                return False

            if lock_obj.is_expired():
                if not self._release(lock_obj):
                    raise DAVCodingError  # pragma: no cover

                return False

            return True

    async def get_lock_objs_from_path(self, path: DAVPath) -> list[DAVLockObj]:
        async with self._asyncio_lock:
            return self._get_lock_objs_from_path(path)

    def _get_lock_objs_from_path(self, path: DAVPath) -> list[DAVLockObj]:
        """get lock_objs from path
        - path is locking by any lock
        - path's parent path's lock is DAVDepth.INFINITY
        """
        now = time()
        lock_obj_expired = set()
        lock_objs: list[DAVLockObj] = list()

        for lock_path, lock_obj_set in self._path2lock_obj_set.items():
            if not lock_path.is_parent_of_or_is_self(path):
                continue

            for lock_obj in list(lock_obj_set.data):
                if lock_obj.is_expired(now=now):
                    lock_obj_expired.add(lock_obj)
                    continue

                if not lock_obj.is_locking_path(path):
                    continue

                lock_objs.append(lock_obj)

        for lock_obj in lock_obj_expired:
            if not self._release(lock_obj):
                raise DAVCodingError  # pragma: no cover

        return lock_objs

    async def has_lock(self, path: DAVPath) -> bool:
        """res path is locking by any lock"""
        async with self._asyncio_lock:
            return len(self._get_lock_objs_from_path(path)) > 0

    def _get_lock_objs_of_child_path_from_path(self, path: DAVPath) -> list[DAVLockObj]:
        """get lock_objs of child path from path"""
        result: list[DAVLockObj] = list()
        for lock_obj_set in self._path2lock_obj_set.values():
            for lock_obj in list(lock_obj_set.data):
                if path.is_parent_of(lock_obj.path):
                    result.append(lock_obj)

        return result
