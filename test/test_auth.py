from base64 import b64encode

import pytest

from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.config import update_config_from_obj, get_config
from asgi_webdav.auth import DAVAuth
from asgi_webdav.request import DAVRequest

USERNAME1 = "user1"
PASSWORD1 = "pass1"

config_data = {
    "account_mapping": [
        {"username": USERNAME1, "password": PASSWORD1, "permissions": list()}
    ]
}

basic_authorization = b"Basic " + b64encode(
    "{}:{}".format(USERNAME1, PASSWORD1).encode("utf-8")
)
basic_authorization_bad = b"Basic bad basic_authorization"


def fake_call():
    pass


request = DAVRequest(
    {"method": "GET", "headers": {b"authorization": b"placeholder"}, "path": "/"},
    fake_call,
    fake_call,
)


@pytest.mark.asyncio
async def test_basic_access_authentication():
    update_config_from_obj(config_data)
    dav_auth = DAVAuth(get_config())

    request.headers.update(
        {
            b"authorization": basic_authorization,
        }
    )
    user, message = await dav_auth.pick_out_user(request)
    print(basic_authorization)
    print(user)
    print(message)
    assert isinstance(user, DAVUser)

    request.headers.update(
        {
            b"authorization": basic_authorization_bad,
        }
    )
    user, message = await dav_auth.pick_out_user(request)
    print(user)
    print(message)
    assert user is None


def test_verify_permission():
    username = USERNAME1
    password = PASSWORD1
    admin = False

    # "+"
    permissions = ["+^/aa"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission([DAVPath("/a")])
    assert dav_user.check_paths_permission([DAVPath("/aa")])
    assert dav_user.check_paths_permission([DAVPath("/aaa")])

    permissions = ["+^/bbb"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission(
        [DAVPath("/aaa")],
    )

    # "-"
    permissions = ["-^/aaa"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert not dav_user.check_paths_permission(
        [DAVPath("/aaa")],
    )

    # "$"
    permissions = ["+^/a$"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/ab")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )

    # multi-rules
    permissions = ["+^/a$", "+^/a/b"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )

    permissions = ["+^/a$", "+^/a/b", "-^/a/b/c"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b/c")],
    )

    permissions = ["+^/a$", "+^/a/b1", "-^/a/b2"]
    dav_user = DAVUser(username, password, permissions, admin)
    assert dav_user.check_paths_permission(
        [DAVPath("/a")],
    )
    assert dav_user.check_paths_permission(
        [DAVPath("/a/b1")],
    )
    assert not dav_user.check_paths_permission(
        [DAVPath("/a/b2")],
    )
