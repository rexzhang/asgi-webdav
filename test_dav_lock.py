from uuid import UUID

import pytest

from asgi_webdav.constants import (
    DAVPath,

)
from asgi_webdav.request import DAVRequest
from asgi_webdav.lock import DAVLock, DAVLockInfo, DAVLockScope


def fake_callable():
    pass


@pytest.mark.asyncio
async def test_lock_basic():
    lock = DAVLock()

    request = DAVRequest(
        scope={
            'method': 'LOCK',
            'path': '/a/b/c',
            'headers': {
                'depth': 0,
                'timeout': 300
            }
        },
        receive=fake_callable,
        send=fake_callable
    )
    request.lock_scope = DAVLockScope.exclusive
    request.lock_owner = 'lock_owner'

    path1 = DAVPath('/a/b/c')
    path1_1 = DAVPath('/a/b')
    path2 = DAVPath('/1/2/3')

    await lock.new(request)
    print(lock)
    assert await lock.is_locking(path1)
    assert not await lock.is_locking(path2)
