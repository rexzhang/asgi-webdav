from datetime import datetime, timedelta

import pytest

from asgi_webdav.cache import DAVCacheBypass, DAVCacheExpiring, DAVCacheMemory


@pytest.mark.asyncio
async def test_cache_bypass() -> None:
    cache = DAVCacheBypass()
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") is None

    await cache.purge()
    assert await cache.get("test") is None


@pytest.mark.asyncio
async def test_cache_memory() -> None:
    cache = DAVCacheMemory()
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") == value

    await cache.purge()
    assert await cache.get("test") is None


@pytest.mark.asyncio
async def test_expiring_cache() -> None:
    cache = DAVCacheExpiring(9999999)
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") == value

    await cache.purge()
    assert await cache.get("test") is None


@pytest.mark.asyncio
async def test_expiring_cache_never_expires() -> None:
    # a negative expiration means entries never expire
    cache = DAVCacheExpiring(-1)

    await cache.set("test", "value")
    assert await cache.get("test") == "value"


@pytest.mark.asyncio
async def test_expiring_cache_expired_entry_popped() -> None:
    cache = DAVCacheExpiring(1)
    await cache.set("test", "value")

    # backdate the entry to force expiration deterministically
    expired = datetime.now() - timedelta(seconds=10)
    cache._cache["test"] = ("value", expired)

    assert await cache.get("test") is None
    # the expired entry was dropped from the cache
    assert "test" not in cache._cache
