from uuid import uuid4

import pytest
from icecream import ic

from asgi_webdav.constants import (
    DAVDepth,
    DAVLockObj,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
)
from asgi_webdav.lock import DAVLockKeeper
from tests.kits.lock import LOCK_RES_PATH1, LOCK_RES_PATH2, RES_OWNER_1


class TestLockExclusiveZero:
    lock_scope: DAVLockScope = DAVLockScope.exclusive
    lock_depth: DAVDepth = DAVDepth.ZERO

    lock_keeper: DAVLockKeeper
    lock_obj1: DAVLockObj | None

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock_keeper = DAVLockKeeper()
        self.lock_obj1 = await self.lock_keeper.new(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH1,
            depth=self.lock_depth,
            scope=self.lock_scope,
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
                depth=self.lock_depth,
                scope=self.lock_scope,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        # but, can not lock some path with exclusive scope, even if the old lock's scope is shared
        assert (
            await self.lock_keeper.new(
                owner=RES_OWNER_1,
                path=LOCK_RES_PATH1,
                depth=self.lock_depth,
                scope=DAVLockScope.shared,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        # can lock other path
        lock_obj2 = await self.lock_keeper.new(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH2,
            depth=self.lock_depth,
            scope=self.lock_scope,
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

        # can not release a lock that does not exist
        lock_obj2 = DAVLockObj(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH2,
            token=uuid4(),
            depth=DAVDepth.ZERO,
            scope=DAVLockScope.exclusive,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert self.lock_keeper._release(lock_obj2) is False

    async def test_is_valid_lock_token(self, mocker):
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

        # expired
        mocker.patch("asgi_webdav.constants.DAVLockObj.is_expired", return_value=True)
        assert (
            await self.lock_keeper.is_valid_lock_token(
                self.lock_obj1.token, LOCK_RES_PATH1
            )
            is False
        )

    async def test_get_lock_objs_from_path(self, mocker):
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH1) == [
            self.lock_obj1
        ]
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH2) == []

    async def test_get_lock_objs_from_path_extra_expired(self, mocker):
        mocker.patch("asgi_webdav.constants.DAVLockObj.is_expired", return_value=True)
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH1) == []

    async def test_get_lock_objs_from_path_extra_check_path_failed(self, mocker):
        mocker.patch("asgi_webdav.constants.DAVLockObj.check_path", return_value=False)
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH1) == []

    async def test_is_locking(self):
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH1) is True
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is False

        _ = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH2,
            depth=self.lock_depth,
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is True


class TestLockSharedZero(TestLockExclusiveZero):
    lock_scope: DAVLockScope = DAVLockScope.shared
    lock_depth: DAVDepth = DAVDepth.ZERO

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock_keeper = DAVLockKeeper()
        self.lock_obj1 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH1,
            depth=self.lock_depth,
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )

    async def test_new(self):
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # can lock same path
        lock_obj2 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH1,
            depth=self.lock_depth,
            scope=self.lock_scope,
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
                depth=self.lock_depth,
                scope=DAVLockScope.exclusive,
                timeout=DAVLockTimeoutMaxValue,
            )
            is None
        )

        # can lock other path
        lock_obj3 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH2,
            depth=self.lock_depth,
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert isinstance(lock_obj3, DAVLockObj)

        assert len(self.lock_keeper._token2lock_obj) == 3
        assert len(self.lock_keeper._path2lock_obj_set) == 2

    async def test_release_extra_for_shared(self):
        # new a shared lock in some path
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1
        lock_obj2 = await self.lock_keeper.new(
            owner="owner",
            path=LOCK_RES_PATH1,
            depth=self.lock_depth,
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert len(self.lock_keeper._token2lock_obj) == 2
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # release a shared lock in some path
        assert await self.lock_keeper.release(lock_obj2.token) is True
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1

        # can not release a shared lock in some path again
        assert self.lock_keeper._release(lock_obj2) is False


class TestLockSharedInfinity(TestLockSharedZero):
    lock_depth: DAVDepth = DAVDepth.INFINITY
