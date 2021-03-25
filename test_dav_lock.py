from uuid import uuid4

import pytest

from asgi_webdav.constants import (
    DAVPath,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.lock import DAVLock, DAVLockInfo, DAVLockScope


def fake_callable():
    pass


def create_request(path: str):
    request = DAVRequest(
        scope={
            "method": "LOCK",
            "path": path,
            "headers": {b"depth": 0, b"timeout": b"Second-300"},
        },
        receive=fake_callable,
        send=fake_callable,
    )
    request.lock_scope = DAVLockScope.exclusive
    request.lock_owner = "lock_owner"
    print(request)
    return request


@pytest.mark.asyncio
async def test_lock_basic():
    lock = DAVLock()
    request1 = create_request("/a/b/c")
    request1.lock_scope = DAVLockScope.exclusive

    path1 = DAVPath("/a/b/c")
    path2 = DAVPath("/1/2/3")

    # new lock
    info1 = await lock.new(request1)
    print(lock)
    print(info1)
    assert await lock.is_locking(path1)
    assert not await lock.is_locking(path1, info1.token)
    assert not await lock.is_locking(path2)

    # lock fail
    info2 = await lock.new(request1)
    assert info2 is None

    # refresh
    assert await lock.refresh(info1.token)
    assert not await lock.refresh(uuid4())
    assert await lock.is_locking(path1)

    # release
    assert not await lock.release(uuid4())
    assert await lock.release(info1.token)
    assert not await lock.is_locking(path1)


@pytest.mark.asyncio
async def test_lock_coll():
    lock = DAVLock()
    request1 = create_request("/a/b/c")
    request1.lock_scope = DAVLockScope.exclusive

    path1 = DAVPath("/a/b/c")
    path2 = DAVPath("/a/b/c/d.txt")

    # new lock
    info1 = await lock.new(request1)
    print(lock)
    print(info1)
    assert await lock.is_locking(path1)
    assert await lock.is_locking(path2)


@pytest.mark.asyncio
async def test_lock_shared():
    lock = DAVLock()

    request1 = create_request("/a/b/c")
    request1.lock_scope = DAVLockScope.shared

    path1 = DAVPath("/a/b/c")
    path2 = DAVPath("/1/2/3")

    # new lock
    info1 = await lock.new(request1)
    assert await lock.is_locking(path1)
    assert not await lock.is_locking(path1, info1.token)
    assert not await lock.is_locking(path2)

    # new lock with shared
    info2 = await lock.new(request1)
    assert isinstance(info2, DAVLockInfo)

    # release
    assert await lock.release(info1.token)
    assert not await lock.release(info1.token)
    assert await lock.release(info2.token)
    assert not await lock.release(info2.token)
