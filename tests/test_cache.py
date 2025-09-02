import pytest

from asgi_webdav.cache import DAVCacheBypass, DAVCacheExpiring, DAVCacheMemory


@pytest.mark.asyncio
async def test_cache_bypass():
    cache = DAVCacheBypass()
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") is None

    await cache.purge()
    assert await cache.get("test") is None


@pytest.mark.asyncio
async def test_cache_memory():
    cache = DAVCacheMemory()
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") == value

    await cache.purge()
    assert await cache.get("test") is None


@pytest.mark.asyncio
async def test_expiring_cache():
    cache = DAVCacheExpiring(9999999)
    value = "value"

    assert await cache.get("test") is None

    await cache.set("test", value)
    assert await cache.get("test") == value

    await cache.purge()
    assert await cache.get("test") is None
