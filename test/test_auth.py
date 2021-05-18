from base64 import b64encode

from asgi_webdav.constants import DAVPath, DAVAccount
from asgi_webdav.config import update_config_from_obj, Account
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

    request.authorization = basic_authorization
    account, message = dav_auth.pick_out_account(request)
    print(basic_authorization)
    print(dav_auth.account_basic_mapping)
    print(account)
    print(message)
    assert isinstance(account, DAVAccount)

    request.authorization = basic_authorization_bad
    account, message = dav_auth.pick_out_account(request)
    print(account)
    print(message)
    assert account is None


def test_verify_permission():
    dav_auth = DAVAuth()
    account_config = Account(
        **{"username": "user1", "password": "pass1", "permissions": list()}
    )

    # "+"
    account_config.permissions = ["+^/aa"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/a")],
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/aa")],
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )

    account_config.permissions = ["+^/bbb"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )

    # "-"
    account_config.permissions = ["-^/aaa"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )

    # "$"
    account_config.permissions = ["+^/a$"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a")],
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/ab")],
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/a/b")],
    )

    # multi-rules
    account_config.permissions = ["+^/a$", "+^/a/b"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a")],
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a/b")],
    )

    account_config.permissions = ["+^/a$", "+^/a/b", "-^/a/b/c"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a")],
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a/b")],
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/a/b/c")],
    )

    account_config.permissions = ["+^/a$", "+^/a/b1", "-^/a/b2"]
    account = DAVAccount(
        account_config.username, account_config.password, account_config.permissions
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a")],
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/a/b1")],
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/a/b2")],
    )
