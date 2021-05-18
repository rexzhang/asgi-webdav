"""
Ref:
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""


from typing import Optional
import re
from base64 import b64encode
from uuid import uuid4
from hashlib import md5
from logging import getLogger

from asgi_webdav.constants import DAVPath, DAVAccount
from asgi_webdav.config import get_config
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse


logger = getLogger(__name__)


MESSAGE_401_TEMPLATE = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>Error</title>
  </head>
  <body>
    <h1>401 Unauthorized. {}</h1>
  </body>
</html>"""


class DAVAuth:
    realm = "ASGI WebDAV"

    account_mapping: dict[str, DAVAccount] = dict()  # username: password
    account_basic_mapping: dict[bytes, DAVAccount] = dict()  # basic string: DAVAccount

    def __init__(self):
        config = get_config()

        for config_account in config.account_mapping:
            basic = b64encode(
                "{}:{}".format(config_account.username, config_account.password).encode(
                    "utf-8"
                )
            )
            account = DAVAccount(
                username=config_account.username,
                password=config_account.password,
                permissions=config_account.permissions,
            )

            self.account_mapping[config_account.username] = account
            self.account_basic_mapping[basic] = account

            logger.info("Register Account: {}".format(account))

    @property
    def digest_nonce(self) -> str:
        return uuid4().hex

    def pick_out_account(self, request: DAVRequest) -> (Optional[DAVAccount], str):
        if request.authorization is None:
            return None, "miss header: authorization"

        # Basic
        if request.authorization[:6] == b"Basic ":
            account = self.account_basic_mapping.get(request.authorization[6:])
            if account is None:
                return None, "no permission"

            return account, ""

        # Digest
        if request.authorization[:7] == b"Digest ":
            """
            HA1 = MD5(username:realm:password)
            HA2 = MD5(method:digestURI)
            """
            data = self._parser_digest_request(request.authorization.decode("utf-8"))
            account = self.account_mapping.get(data.get("username"))
            if account is None:
                return None, "no permission"
            ha1 = md5(
                "{}:{}:{}".format(
                    account.username, self.realm, account.password
                ).encode("utf-8")
            ).hexdigest()
            ha2 = md5(
                "{}:{}".format(request.method, data.get("uri")).encode("utf-8")
            ).hexdigest()
            if "auth" in data.get("qop"):
                # MD5(HA1:nonce:nonceCount:cnonce:qop:HA2)
                response = md5(
                    "{}:{}:{}:{}:{}:{}".format(
                        ha1,
                        data.get("nonce"),
                        data.get("nc"),
                        data.get("cnonce"),
                        data.get("qop"),
                        ha2,
                    ).encode("utf-8")
                ).hexdigest()
            else:
                # MD5(HA1:nonce:HA2)
                response = md5(
                    "{}:{}:{}".format(ha1, data.get("nonce"), ha2).encode("utf-8")
                ).hexdigest()

            if data.get("response") == response:
                return account, ""

            return None, "no permission"

        return None, "Unknown authentication method"

    @staticmethod
    def verify_permission(account: DAVAccount, paths: list[DAVPath]) -> bool:
        for path in paths:
            allow = False
            for permission in account.permissions_allow:  # allow: or
                m = re.match(permission, path.raw)
                if m is not None:
                    allow = True
                    break

            if not allow:
                return False

        for path in paths:
            allow = True
            for permission in account.permissions_deny:  # deny: and
                m = re.match(permission, path.raw)
                if m is not None:
                    allow = False
                    break

            if not allow:
                return False

        return True

    def create_response_401(self, message: str) -> DAVResponse:
        headers = {
            b"WWW-Authenticate": 'Digest realm="{}", qop="auth", nonce="{}"'.format(
                # b"WWW-Authenticate": 'Digest realm="{}", nonce="{}"'.format(
                self.realm,
                self.digest_nonce,
            ).encode("utf-8")
        }
        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(status=401, data=message_401, headers=headers)

    @staticmethod
    def _parser_digest_request(authorization: str) -> dict:
        values = authorization[7:].split(",")

        data = dict()
        for value in values:
            value = value.replace('"', "").replace(" ", "")
            try:
                k, v = value.split("=")
                data[k] = v
            except ValueError:
                pass

        print(data)
        return data
