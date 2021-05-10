"""
Ref:
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""


from typing import Dict, Optional, List
import re
from base64 import b64encode
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

    account_basic_mapping: Dict[bytes, DAVAccount] = dict()  # basic string: DAVAccount

    def __init__(self):
        config = get_config()
        for config_account in config.account_mapping:
            basic = b64encode(
                "{}:{}".format(config_account.username, config_account.password).encode(
                    "utf-8"
                )
            )
            account = DAVAccount(
                username=config_account.username, permissions=config_account.permissions
            )

            self.account_basic_mapping[basic] = account
            logger.info("Register Account: {}".format(account))

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
        if request.authorization[:6] == b"Digest":
            # TODO
            return None, "Digest is not currently supported"

        return None, "Unknown authentication method"

    @staticmethod
    def verify_permission(account: DAVAccount, paths: List[DAVPath]) -> bool:
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
            b"WWW-Authenticate": 'Basic realm="{}"'.format(self.realm).encode("utf-8")
        }
        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(status=401, message=message_401, headers=headers)
