from asyncio import Lock
from enum import auto
from logging import getLogger

from asgi_webdav.constants import DAVUpperEnumAbc

logger = getLogger(__name__)


class DAVCacheType(DAVUpperEnumAbc):
    BYPASS = auto()
    MEMORY = auto()


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


# TODO: RedisCache
