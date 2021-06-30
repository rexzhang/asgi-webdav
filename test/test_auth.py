from base64 import b64encode

from asgi_webdav.constants import DAVPath, DAVUser
from asgi_webdav.config import update_config_from_obj
from asgi_webdav.auth import DAVAuth
from asgi_webdav.request import DAVRequest


config_data = {
    "account_mapping": [
        {"username": "user1", "password": "pass1", "permissions": list()}
    ]
}

basic_authorization = b"Basic " + b64encode(
    "{}:{}".format("user1", "pass1").encode("utf-8")
)
basic_authorization_bad = b"Basic bad basic_authorization"


def fake_call():
    pass


request = DAVRequest(
    {"method": "GET", "headers": {b"authorization": b"placeholder"}, "path": "/"},
    fake_call,
    fake_call,
)


def test_basic_access_authentication():
    update_config_from_obj(config_data)
    dav_auth = DAVAuth()

    request.headers.update(
        {
            b"authorization": basic_authorization,
        }
    )
    account, message = dav_auth.pick_out_user(request)
    print(basic_authorization)
    print(dav_auth.basic_auth.credential_user_mapping)
    print(account)
    print(message)
    assert isinstance(account, DAVUser)

    request.headers.update(
        {
            b"authorization": basic_authorization_bad,
        }
    )
    account, message = dav_auth.pick_out_user(request)
    print(account)
    print(message)
    assert account is None


def test_verify_permission():
    username = "user1"
    password = "pass1"
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
