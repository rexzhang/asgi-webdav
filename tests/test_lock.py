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
from tests.kits.lock import LOCK_RES_PATH1, LOCK_RES_PATH2, RES_OWNER_1


async def test_DAVLockKeeper_new_from_empty():
    lock_keeper = DAVLockKeeper()
    assert len(lock_keeper._token2lock_obj) == 0
    assert len(lock_keeper._path2lock_obj_set) == 0

    lock_obj1 = await lock_keeper.new(
        owner=RES_OWNER_1,
        path=LOCK_RES_PATH1,
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=DAVLockTimeoutMaxValue,
    )
    assert lock_obj1 is not None
    assert len(lock_keeper._token2lock_obj) == 1
    assert len(lock_keeper._path2lock_obj_set) == 1


@pytest.mark.parametrize(
    "owner,path,depth,scope,timeout,expected",
    [
        (
            RES_OWNER_1,
            DAVPath("/parent_ZERO_EXCLUSIVE/test"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_ZERO_SHARED/test"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_INFINITY_EXCLUSIVE/test"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_INFINITY_EXCLUSIVE/test"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_INFINITY_SHARED/test"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_INFINITY_SHARED/test"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            True,
        ),
        # ---
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_EXCLUSIVE"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_EXCLUSIVE"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_SHARED"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_SHARED"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            True,
        ),
        # ---
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_EXCLUSIVE"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_EXCLUSIVE"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_EXCLUSIVE"),
            DAVDepth.INFINITY,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_EXCLUSIVE"),
            DAVDepth.INFINITY,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_SHARED"),
            DAVDepth.ZERO,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_SHARED"),
            DAVDepth.ZERO,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            True,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_SHARED"),
            DAVDepth.INFINITY,
            DAVLockScope.EXCLUSIVE,
            DAVLockTimeoutMaxValue,
            False,
        ),
        (
            RES_OWNER_1,
            DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_SHARED"),
            DAVDepth.INFINITY,
            DAVLockScope.SHARED,
            DAVLockTimeoutMaxValue,
            True,
        ),
    ],
)
async def test_DAVLockKeeper_new(
    owner: str,
    path: DAVPath,
    depth: DAVDepth,
    scope: DAVLockScope,
    timeout: int,
    expected: bool,
):
    # init
    lock_keeper = DAVLockKeeper()
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_ZERO_EXCLUSIVE"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=DAVLockTimeoutMaxValue,
    )
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_ZERO_SHARED"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.SHARED,
        timeout=DAVLockTimeoutMaxValue,
    )
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_INFINITY_EXCLUSIVE"),
        depth=DAVDepth.INFINITY,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=DAVLockTimeoutMaxValue,
    )
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_INFINITY_SHARED"),
        depth=DAVDepth.INFINITY,
        scope=DAVLockScope.SHARED,
        timeout=DAVLockTimeoutMaxValue,
    )
    # ---
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_UNLOCKED/res_EXCLUSIVE"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=DAVLockTimeoutMaxValue,
    )
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_UNLOCKED/res_SHARED"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.SHARED,
        timeout=DAVLockTimeoutMaxValue,
    )
    # ---
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_EXCLUSIVE/child"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.EXCLUSIVE,
        timeout=DAVLockTimeoutMaxValue,
    )
    await lock_keeper.new(
        owner=RES_OWNER_1,
        path=DAVPath("/parent_UNLOCKED/res_UNLOCKED_child_SHARED/child"),
        depth=DAVDepth.ZERO,
        scope=DAVLockScope.SHARED,
        timeout=DAVLockTimeoutMaxValue,
    )

    # test
    lock_obj = DAVLockObj(
        owner=owner, path=path, depth=depth, token=uuid4(), scope=scope, timeout=timeout
    )
    ic(lock_obj)

    assert (
        lock_keeper._new(
            lock_obj,
            lock_objs_of_path=None,
        )
        is expected
    )


class TestLockExclusiveZero:
    lock_scope: DAVLockScope = DAVLockScope.EXCLUSIVE
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
        ic(self.lock_keeper._token2lock_obj)
        ic(self.lock_keeper._path2lock_obj_set)
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
            scope=DAVLockScope.EXCLUSIVE,
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

    async def test_get_lock_objs_from_path_extra_is_locking_path_failed(self, mocker):
        mocker.patch(
            "asgi_webdav.constants.DAVLockObj.is_locking_path", return_value=False
        )
        assert await self.lock_keeper.get_lock_objs_from_path(LOCK_RES_PATH1) == []

    async def test_is_locking(self):
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH1) is True
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is False

        _ = await self.lock_keeper.new(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH2,
            depth=self.lock_depth,
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )
        assert await self.lock_keeper.has_lock(LOCK_RES_PATH2) is True


class TestLockSharedZero(TestLockExclusiveZero):
    lock_scope: DAVLockScope = DAVLockScope.SHARED
    lock_depth: DAVDepth = DAVDepth.ZERO

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

    async def test_release_extra_for_shared(self):
        # new a shared lock in some path
        assert len(self.lock_keeper._token2lock_obj) == 1
        assert len(self.lock_keeper._path2lock_obj_set) == 1
        lock_obj2 = await self.lock_keeper.new(
            owner=RES_OWNER_1,
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
