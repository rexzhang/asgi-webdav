from time import time
from uuid import UUID

import pytest

from asgi_webdav.constants import (
    DAVDepth,
    DAVLockObj,
    DAVLockScope,
    DAVLockTimeoutMaxValue,
)
from tests.kits.lock import LOCK_RES_PATH1, LOCK_RES_PATH2, LOCK_UUID_1, RES_OWNER_1


class TestDAVLockObj:
    lock_scope: DAVLockScope = DAVLockScope.EXCLUSIVE
    lock_depth: DAVDepth = DAVDepth.ZERO

    @pytest.fixture(autouse=True)
    async def init_per_test(self):
        self.lock_obj1 = DAVLockObj(
            owner=RES_OWNER_1,
            path=LOCK_RES_PATH1,
            depth=self.lock_depth,
            token=UUID(LOCK_UUID_1),
            scope=self.lock_scope,
            timeout=DAVLockTimeoutMaxValue,
        )

    def test_hash(self):
        assert self.lock_obj1.hash_value == hash(UUID(LOCK_UUID_1))

    def test_expire(self, mocker):
        now = time()
        timeout = 10
        mocker.patch("asgi_webdav.constants.time", return_value=now)

        self.lock_obj1.timeout = timeout
        self.lock_obj1.update_expire()
        assert self.lock_obj1.is_expired() is False
        assert self.lock_obj1.is_expired(now + 5) is False
        assert self.lock_obj1.is_expired(now + 99) is True

    def test_check_path(self):
        # DAVDepth.ZERO
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH1) is True
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH1.parent) is False
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH2) is False

        # DAVDepth.INFINITY
        self.lock_obj1.depth = DAVDepth.INFINITY
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH1) is True
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH1.add_child("test")) is True
        assert self.lock_obj1.is_locking_path(LOCK_RES_PATH2) is False
