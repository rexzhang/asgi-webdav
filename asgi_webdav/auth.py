"""
Ref:
- https://tools.ietf.org/html/rfc2617
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication

- https://github.com/dimagi/python-digest/blob/master/python_digest/utils.py
- https://gist.github.com/dayflower/5828503
"""


from typing import Dict, Optional
import re
from base64 import b64encode
from logging import getLogger

from asgi_webdav.constants import DAVPath
from asgi_webdav.config import Config, Account
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

    basic_data_mapping: Dict[bytes, Account] = dict()  # basic string: Account

    def __init__(self, config: Config):
        for account in config.account_mapping:
            basic = b64encode(
                "{}:{}".format(account.username, account.password).encode("utf-8")
            )
            self.basic_data_mapping[basic] = account

            logger.info("Register Account: {}".format(account))

    def pick_out_account(self, request: DAVRequest) -> (Optional[Account], str):
        if request.authorization is None:
            return None, "miss header: authorization"

        # Basic
        if request.authorization[:6] == b"Basic ":
            account = self.basic_data_mapping.get(request.authorization[6:])
            if account is None:
                return None, "no permission"

            return account, ""

        # Digest
        if request.authorization[:6] == b"Digest":
            # TODO
            return None, "Digest is not currently supported"

        return None, "Unknown authentication method"

    @staticmethod
    def verify_permission(account: Account, paths: list[DAVPath]) -> bool:
        for permission in account.permissions:
            pattern = permission[1:]
            for path in paths:
                m = re.match(pattern, path.raw)

                if permission[0] == "+":
                    if m is None:
                        return False
                    else:
                        return True

                elif permission[0] == "-":
                    if m is None:
                        return True
                    else:
                        return False

        return False

    def create_response_401(self, message: str) -> DAVResponse:
        headers = {
            b"WWW-Authenticate": 'Basic realm="{}"'.format(self.realm).encode("utf-8")
        }
        message_401 = MESSAGE_401_TEMPLATE.format(message).encode("utf-8")
        return DAVResponse(status=401, message=message_401, headers=headers)
