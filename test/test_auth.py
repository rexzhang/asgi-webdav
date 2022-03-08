from base64 import b64encode

import pytest

from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.config import update_config_from_obj, get_config
from asgi_webdav.auth import DAVPassword, DAVPasswordType, DAVAuth
from asgi_webdav.request import DAVRequest

USERNAME = "username"
PASSWORD = "password"
HASHLIB_USER = "user-hashlib"


basic_authorization = b"Basic " + b64encode(
    "{}:{}".format(USERNAME, PASSWORD).encode("utf-8")
)
basic_authorization_bad = b"Basic bad basic_authorization"


def get_basic_authorization(username, password) -> bytes:
    return b"Basic " + b64encode("{}:{}".format(username, password).encode("utf-8"))


def fake_call():
    pass


request = DAVRequest(
    {"method": "GET", "headers": {b"authorization": b"placeholder"}, "path": "/"},
    fake_call,
    fake_call,
)


def test_dev_password_class():
    pw_obj = DAVPassword("password")
    assert pw_obj.type == DAVPasswordType.RAW

    pw_obj = DAVPassword(
        "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b"
    )
    assert pw_obj.type == DAVPasswordType.HASHLIB

    pw_obj = DAVPassword("<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567")
    assert pw_obj.type == DAVPasswordType.DIGEST

    pw_obj = DAVPassword(
        "<ldap>#1#ldaps://rexzhang.myds.me#SIMPLE#"
        "uid=user-ldap,cn=users,dc=rexzhang,dc=myds,dc=me"
    )
    assert pw_obj.type == DAVPasswordType.LDAP


@pytest.mark.asyncio
async def test_basic_access_authentication():
    config_data = {
        "account_mapping": [
            {"username": USERNAME, "password": PASSWORD, "permissions": list()},
            {
                "username": HASHLIB_USER,
                "password": "<hashlib>:sha256:salt:"
                "291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
                "permissions": list(),
            },
        ]
    }
    update_config_from_obj(config_data)
    dav_auth = DAVAuth(get_config())

    request.headers[b"authorization"] = get_basic_authorization(USERNAME, PASSWORD)
    user, message = await dav_auth.pick_out_user(request)
    print(basic_authorization)
    print(user)
    print(message)
    assert isinstance(user, DAVUser)

    request.headers[b"authorization"] = get_basic_authorization(HASHLIB_USER, PASSWORD)
    user, message = await dav_auth.pick_out_user(request)
    assert isinstance(user, DAVUser)

    request.headers[b"authorization"] = basic_authorization_bad
    user, message = await dav_auth.pick_out_user(request)
    print(user)
    print(message)
    assert user is None


def test_verify_permission():
    username = USERNAME
    password = PASSWORD
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
