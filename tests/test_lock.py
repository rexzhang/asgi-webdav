from uuid import uuid4

import pytest
from icecream import ic

from asgi_webdav.constants import (
    DAVDepth,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
    DAVPath,
)
from asgi_webdav.lock import DAVLock

from .testkit_asgi import create_dav_request_object


def create_request(path: str):
    request = create_dav_request_object(
        method="LOCK",
        path=path,
        headers={"depth": "0", "timeout": "Second-300"},
    )
    request.lock_scope = DAVLockScope.exclusive
    request.lock_owner = "lock_owner"
    print(request)
    return request


LOCK_RES_PATH1 = DAVPath("/a/b/c")
LOCK_RES_PATH2 = DAVPath("/1/2/3")


class TestLockExclusive:

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock = DAVLock()
        self.info1 = await self.lock.new(
            LOCK_RES_PATH1,
            DAVDepth.d0,
            DAVLockTimeoutMaxValue,
            DAVLockScope.exclusive,
            "owner",
        )

    async def test_new(self):
        assert await self.lock.is_locking(LOCK_RES_PATH1) is True
        assert await self.lock.is_locking(LOCK_RES_PATH1, self.info1.token) is False
        assert await self.lock.is_locking(LOCK_RES_PATH2) is False

        assert (
            await self.lock.is_valid_lock_token(self.info1.token, LOCK_RES_PATH1)
            is True
        )

    async def test_new_some_res_path(self):
        # new fail
        info2 = await self.lock.new(
            LOCK_RES_PATH1,
            DAVDepth.d0,
            DAVLockTimeoutMaxValue,
            DAVLockScope.exclusive,
            "owner",
        )
        assert info2 is None

    async def test_refresh(self):
        # refresh
        assert await self.lock.refresh(self.info1.token) is not None

        # refresh fail
        assert not await self.lock.refresh(uuid4()) is not None

    async def test_lock_coll(self):
        assert await self.lock.is_locking(LOCK_RES_PATH1)
        assert await self.lock.is_locking(LOCK_RES_PATH1.add_child("d.txt"))

    async def test_release(self):
        assert await self.lock.is_locking(LOCK_RES_PATH1) is True
        assert await self.lock.release(self.info1.token) is True

        assert await self.lock.release(self.info1.token) is False
        assert await self.lock.is_locking(LOCK_RES_PATH1) is False

    async def test_get_info_by_path(self):
        assert await self.lock.get_info_by_path(LOCK_RES_PATH1) == [self.info1]
        assert await self.lock.get_info_by_path(LOCK_RES_PATH2) == []

    async def test_get_info_by_token(self):
        assert await self.lock.get_info_by_token(self.info1.token) == self.info1
        assert await self.lock.get_info_by_token(uuid4()) is None

    async def test_is_valid_lock_token(self):
        assert (
            await self.lock.is_valid_lock_token(self.info1.token, LOCK_RES_PATH1)
            is True
        )
        assert await self.lock.is_valid_lock_token(uuid4(), LOCK_RES_PATH1) is False
        assert (
            await self.lock.is_valid_lock_token(self.info1.token, LOCK_RES_PATH2)
            is False
        )
        assert await self.lock.is_valid_lock_token(uuid4(), LOCK_RES_PATH2) is False


class TestLockShared(TestLockExclusive):

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock = DAVLock()
        self.info1 = await self.lock.new(
            LOCK_RES_PATH1,
            DAVDepth.d0,
            DAVLockTimeoutMaxValue,
            DAVLockScope.shared,
            "owner",
        )

    async def test_new_some_res_path(self):
        # new shared
        info2 = await self.lock.new(
            LOCK_RES_PATH1,
            DAVDepth.d0,
            DAVLockTimeoutMaxValue,
            DAVLockScope.shared,
            "owner",
        )
        ic(info2)
        assert info2.path == self.info1.path
        assert info2.token != self.info1.token
