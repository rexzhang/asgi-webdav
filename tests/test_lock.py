from uuid import uuid4

import pytest
from icecream import ic

from asgi_webdav.constants import (
    DAVDepth,
    DAVLockObj,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
    DAVPath,
)
from asgi_webdav.lock import DAVLockKeeper
from tests.kits.lock import RES_OWNER_1

LOCK_RES_PATH1 = DAVPath("/a/b/c")
LOCK_RES_PATH2 = DAVPath("/1/2/3")


class TestLockExclusive:
    lock_keeper: DAVLockKeeper
    lock_obj1: DAVLockObj | None

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock_keeper = DAVLockKeeper()
        self.lock_obj1 = await self.lock_keeper.new(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH1,
            depth=DAVDepth.d0,
            scope=DAVLockScope.exclusive,
            timeout=DAVLockTimeoutMaxValue,
        )

    async def test_get(self, mocker):
        assert await self.lock_keeper.get(self.lock_obj1.token) is self.lock_obj1
        assert await self.lock_keeper.get(uuid4()) is None

        # expired
        mocker.patch("asgi_webdav.constants.DAVLockObj.is_expired", return_value=True)
        mocker.patch("asgi_webdav.lock.DAVLockKeeper._release", return_value=None)
        assert await self.lock_keeper.get(self.lock_obj1.token) is None
        mocker.stopall()

        # for DAVLockObj
        assert await self.lock_keeper.get(self.lock_obj1.token) == self.lock_obj1

        self.lock_obj1 != "abc"

    async def test_new(self):
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # can't lock same path
        assert (
            await self.lock_keeper.new(
                owner=RES_OWNER_1,
                path=LOCK_RES_PATH1,
                depth=DAVDepth.d0,
                scope=DAVLockScope.exclusive,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        assert (
            await self.lock_keeper.new(
                owner=RES_OWNER_1,
                path=LOCK_RES_PATH1,
                depth=DAVDepth.d0,
                scope=DAVLockScope.shared,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        # can lock other path
        lock_obj2 = await self.lock_keeper.new(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH2,
            depth=DAVDepth.d0,
            scope=DAVLockScope.exclusive,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert isinstance(lock_obj2, DAVLockObj)

        assert len(self.lock_keeper._token2lock_obj) == 2
        assert len(self.lock_keeper._path2lock_obj_set) == 2

    async def test_refresh(self):
        # refresh
        lock_obj2 = await self.lock_keeper.refresh(self.lock_obj1)
        ic(lock_obj2)
        assert isinstance(lock_obj2, DAVLockObj)

        assert await self.lock_keeper.has_lock(LOCK_RES_PATH1) is True
        assert await self.lock_keeper.is_valid_lock_token(
            lock_obj2.token, LOCK_RES_PATH1
        )

        # with new timeout value
        lock_obj3 = await self.lock_keeper.refresh(lock_obj2, timeout=99999)
        ic(lock_obj3)
        assert isinstance(lock_obj3, DAVLockObj)

    async def test_release(self):
        assert await self.lock_keeper.release(self.lock_obj1.token) is True
        assert len(self.lock_keeper._token2lock_obj) == 0
        assert len(self.lock_keeper._path2lock_obj_set) == 0

        assert await self.lock_keeper.release(self.lock_obj1.token) is False

    async def test_is_valid_lock_token(self):
        assert (
            await self.lock_keeper.is_valid_lock_token(
                self.lock_obj1.token, LOCK_RES_PATH1
            )
            is True
        )
        assert (
            await self.lock_keeper.is_valid_lock_token(uuid4(), LOCK_RES_PATH1) is False
        )
        assert (
            await self.lock_keeper.is_valid_lock_token(
                self.lock_obj1.token, LOCK_RES_PATH2
            )
            is False
        )
        assert (
            await self.lock_keeper.is_valid_lock_token(uuid4(), LOCK_RES_PATH2) is False
        )

    async def test_get_lock_objs_from_path(self):
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH1) == [
            self.lock_obj1
        ]
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH2) == []

    async def test_is_locking(self):
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH1) is True
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is False

        _ = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH2,
            depth=DAVDepth.d0,
            scope=DAVLockScope.exclusive,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is True


class TestLockShared(TestLockExclusive):

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock_keeper = DAVLockKeeper()
        self.lock_obj1 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH1,
            depth=DAVDepth.d0,
            scope=DAVLockScope.shared,
            timeout=DAVLockTimeoutMaxValue,
        )

    async def test_new(self):
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # can lock same path
        lock_obj2 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH1,
            depth=DAVDepth.d0,
            scope=DAVLockScope.shared,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert isinstance(lock_obj2, DAVLockObj)

        assert len(self.lock_keeper._token2lock_obj) == 2
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # but, can not lock some path with exclusive scope
        assert (
            await self.lock_keeper.new(
                owner="owner",
                path=LOCK_RES_PATH1,
                depth=DAVDepth.d0,
                scope=DAVLockScope.exclusive,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        # can lock other path
        lock_obj3 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH2,
            depth=DAVDepth.d0,
            scope=DAVLockScope.shared,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert isinstance(lock_obj3, DAVLockObj)

        assert len(self.lock_keeper._token2lock_obj) == 3
        assert len(self.lock_keeper._path2lock_obj_set) == 2
