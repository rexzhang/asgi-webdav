from base64 import b64encode

from asgi_webdav.constants import DAVPath
from asgi_webdav.config import Config, Account
from asgi_webdav.auth import DAVAuth
from asgi_webdav.request import DAVRequest


config = Config()
config.account_mapping.append(
    Account(**{"username": "user1", "password": "pass1", "permissions": []})
)

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


def test_extract_account():
    dav_auth = DAVAuth(config)

    request.authorization = basic_authorization
    account, message = dav_auth.pick_out_account(request)
    print(basic_authorization)
    print(dav_auth.basic_data_mapping)
    print(account)
    print(message)
    assert isinstance(account, Account)

    request.authorization = basic_authorization_bad
    account, message = dav_auth.pick_out_account(request)
    print(account)
    print(message)
    assert account is None


def test_verify_permission():
    dav_auth = DAVAuth(config)

    # "+"
    account = Account(
        **{"username": "user1", "password": "pass1", "permissions": ["+^/aa"]}
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

    account = Account(
        **{"username": "user1", "password": "pass1", "permissions": ["+^/bbb"]}
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )

    # "-"
    account = Account(
        **{"username": "user1", "password": "pass1", "permissions": ["-^/aaa"]}
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )

    # "$"
    account = Account(
        **{"username": "user1", "password": "pass1", "permissions": ["+^/aa$"]}
    )
    assert dav_auth.verify_permission(
        account,
        [DAVPath("/aa")],
    )
    assert not dav_auth.verify_permission(
        account,
        [DAVPath("/aaa")],
    )
