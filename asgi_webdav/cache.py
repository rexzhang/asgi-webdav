from asyncio import Lock
from datetime import datetime, timedelta
from enum import auto
from logging import getLogger
from typing import Any

from asgi_webdav.constants import DAVUpperEnumAbc

logger = getLogger(__name__)


class DAVCacheType(DAVUpperEnumAbc):
    BYPASS = auto()
    MEMORY = auto()
    EXPIRING = auto()


class DAVCacheAbc:  # pragma: no cover
    async def prepare(self):
        raise NotImplementedError

    async def get(self, key):
        raise NotImplementedError

    async def set(self, key, value):
        raise NotImplementedError

    async def purge(self) -> None:
        raise NotImplementedError

    async def close(self):
        raise NotImplementedError


class DAVCacheBypass(DAVCacheAbc):
    async def prepare(self):  # pragma: no cover
        pass

    async def get(self, key):
        return None

    async def set(self, key, value):
        pass

    async def purge(self) -> None:
        pass

    async def close(self):  # pragma: no cover
        pass


class DAVCacheMemory(DAVCacheAbc):
    _lock: Lock
    _cache: dict

    def __init__(self) -> None:
        self._cache = {}
        self._lock = Lock()

    async def prepare(self):  # pragma: no cover
        pass

    async def get(self, key):
        async with self._lock:
            return self._cache.get(key)

    async def set(self, key, value):
        async with self._lock:
            self._cache[key] = value

    async def purge(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def close(self):  # pragma: no cover
        pass


class DAVCacheExpiring(DAVCacheAbc):
    _lock: Lock
    _cache: dict[bytes, tuple[Any, datetime]]
    _cache_expiration_timedelta: timedelta

    def __init__(self, cache_expiration: int) -> None:
        self._cache = {}
        self._lock = Lock()
        if cache_expiration < 0:
            self._cache_expiration_timedelta = timedelta.max
        else:
            self._cache_expiration_timedelta = timedelta(seconds=cache_expiration)

    async def prepare(self):  # pragma: no cover
        pass

    async def get(self, key):
        async with self._lock:
            cached = self._cache.get(key)
            if cached:
                user, timestamp = cached
                if datetime.now() - timestamp < self._cache_expiration_timedelta:
                    return user

                # Cache entry expired
                self._cache.pop(key, None)

    async def set(self, key, value):
        async with self._lock:
            self._cache[key] = (value, datetime.now())

    async def purge(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def close(self):  # pragma: no cover
        pass


# TODO: RedisCache
