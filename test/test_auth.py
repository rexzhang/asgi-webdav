from base64 import b64encode

from asgi_webdav.config import Config, Account
from asgi_webdav.auth import DAVAuth


config = Config()
config.account_mapping.append(
    Account(**{"username": "user1", "password": "pass1", "permissions": []})
)

basic_authorization = b"Basic " + b64encode(
    "{}:{}".format("user1", "pass1").encode("utf-8")
)


def test_verify_account():
    dav_auth = DAVAuth(config)

    account, message = dav_auth.verify_account(basic_authorization)
    print(basic_authorization)
    print(dav_auth.basic_data_mapping)
    print(account)
    print(message)
    assert isinstance(account, Account)
    account, message = dav_auth.verify_account(b"Basic bad basic_authorization")
    print(account)
    print(message)
    assert account is None
