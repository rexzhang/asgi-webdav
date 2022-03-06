"""
Ref:
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication
- https://datatracker.ietf.org/doc/html/rfc2617
- https://datatracker.ietf.org/doc/html/rfc7616
- https://datatracker.ietf.org/doc/html/rfc7617
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Authentication
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Digest

- https://github.com/dimagi/python-digest/blob/master/python_digest/__init__.py
- https://github.com/psf/requests/blob/master/requests/auth.py
- https://gist.github.com/dayflower/5828503

LDAP
- https://www.openldap.org/doc/admin24/security.html
"""
import binascii
import re
import hashlib
import asyncio
from base64 import b64decode
from uuid import uuid4
from logging import getLogger

import bonsai
from bonsai import errors as bonsai_exception

from asgi_webdav.constants import DAVUser
from asgi_webdav.exception import AuthFailedException
from asgi_webdav.config import Config, User as ConfigUser
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse


logger = getLogger(__name__)


class HTTPAuthAbc:
    realm: str

    def __init__(self, realm: str):
        self.realm = realm

    @staticmethod
    def is_credential(authorization_header: bytes) -> bool:
        raise NotImplementedError

    def make_auth_challenge_string(self) -> bytes:
        raise NotImplementedError


class HTTPBasicAuth(HTTPAuthAbc):
    _cache: dict[bytes, DAVUser]  # basic string: DAVUser
    _cache_lock: asyncio.Lock

    def __init__(self, realm: str):
        super().__init__(realm=realm)

        self._cache_lock = asyncio.Lock()
        self._cache = dict()

    @staticmethod
    def is_credential(auth_header_type: bytes) -> bool:
        return auth_header_type.lower() == b"basic"

    def make_auth_challenge_string(self) -> bytes:
        return 'Basic realm="{}"'.format(self.realm).encode("utf-8")

    async def get_user_from_cache(self, auth_header_data: bytes) -> DAVUser | None:
        async with self._cache_lock:
            return self._cache.get(auth_header_data)

    async def update_user_to_cache(
        self, auth_header_data: bytes, user: DAVUser
    ) -> None:
        async with self._cache_lock:
            self._cache.update({auth_header_data: user})
        return

    @staticmethod
    def parser_auth_header_data(auth_header_data: bytes) -> (str, str):
        try:
            data = b64decode(auth_header_data).decode("utf-8")  # TODO try
        except binascii.Error:
            raise AuthFailedException()

        index = data.find(":")
        if index == -1:
            raise AuthFailedException()

        return data[:index], data[index + 1 :]


DIGEST_AUTHORIZATION_PARAMS = {
    "username",
    "realm",
    "nonce",
    "uri",
    "response",
    "algorithm",
    "opaque",
    "qop",
    "nc",
    "cnonce",
}


class HTTPDigestAuth(HTTPAuthAbc):
    # https://datatracker.ietf.org/doc/html/rfc7616#section-3.5
    # The Authentication-Info header field is allowed in the trailer of an
    # HTTP message transferred via chunked transfer coding.
    #
    # For historical reasons, a sender MUST only generate the quoted string
    # syntax for the following parameters: nextnonce, rspauth, and cnonce.
    #
    # For historical reasons, a sender MUST NOT generate the quoted string
    # syntax for the following parameters: qop and nc.
    #
    # For historical reasons, the nc value MUST be exactly 8 hexadecimal
    # digits.

    # http://www.webdav.org/neon/doc/html/compliance.html#idm140606748304208
    # neon is not strictly compliant with the quoting rules given in the grammar for
    # the Authorization header. The grammar requires that the qop and algorithm
    # parameters are not quoted, however one widely deployed server implementation
    # (Microsoft® IIS 5) rejects the request if these parameters are not quoted. neon
    # sends these parameters with quotes—this is not known to cause any problems with
    # other server implementations.

    def __init__(self, realm: str, secret: str | None = None):
        super().__init__(realm=realm)

        if secret is None:
            self.secret = uuid4().hex
        else:
            self.secret = secret

        self.opaque = uuid4().hex.upper()

    @staticmethod
    def is_credential(auth_header_type: bytes) -> bool:
        return auth_header_type.lower() == b"digest"

    def make_auth_challenge_string(self) -> bytes:
        return "Digest {}".format(
            self.authorization_string_build_from_data(
                {
                    "realm": self.realm,
                    "qop": "auth",
                    "nonce": self.nonce,
                    "opaque": self.opaque,
                    "algorithm": "MD5",
                    "stale": "false",
                }
            )
        ).encode("utf-8")
        # f_str = (
        #     'Digest realm="{}", nonce="{}", opaque="{}",'
        #     ' qop=auth, algorithm=MD5, stale="false"'
        # )
        # return f_str.format(self.realm, self.nonce, self.opaque).encode("utf-8")
        # f_str = 'Digest realm="{}", nonce="{}",
        # opaque="{}", qop="auth", algorithm=MD5'
        # return f_str.format(self.realm, self.nonce, self.opaque).encode("utf-8")

    def make_response_authentication_info_string(
        self,
        request: DAVRequest,
        user: DAVUser,
        digest_auth_data: dict[str, str],
    ) -> bytes:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=user.username,
            password=user.password,
            method=request.method,
            uri=digest_auth_data.get("uri"),  # TODO!!!,
        )
        rspauth = self.build_md5_digest(
            [
                ha1,
                digest_auth_data.get("nonce"),
                digest_auth_data.get("nc"),
                digest_auth_data.get("cnonce"),
                digest_auth_data.get("qop"),
                ha2,
            ]
        )
        return self.authorization_string_build_from_data(
            {
                "rspauth": rspauth,
                "qop": digest_auth_data.get("qop"),
                "cnonce": digest_auth_data.get("cnonce"),
                "nc": digest_auth_data.get("nc"),
            }
        ).encode("utf-8")
        # return 'rspauth="{}", cnonce="{}", qop={}, nc={}'.format(
        #     rspauth,
        #     digest_auth_data.get("cnonce"),
        #     digest_auth_data.get("qop"),
        #     digest_auth_data.get("nc"),
        # ).encode("utf-8")

    @property
    def nonce(self) -> str:
        return hashlib.new(
            "md5", "{}{}".format(uuid4().hex, self.secret).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def authorization_str_parser_to_data(authorization: str) -> dict:
        values = authorization.split(",")
        data = dict()
        for value in values:
            try:
                k, v = value.split("=", maxsplit=1)
                k = k.strip(" ").rstrip(" ")
                v = v.strip(' "').rstrip(' "').strip("'").rstrip("'")
                data[k] = v
            except ValueError as e:
                logger.error("parser:{} failed, ".format(value), e)

        logger.debug("Digest string data:{}".format(data))
        return data

    @staticmethod
    def authorization_string_build_from_data(data: dict[str, str]) -> str:
        return ", ".join(['%s="%s"' % (k, v) for (k, v) in data.items()])

    @staticmethod
    def build_md5_digest(data: list[str]) -> str:
        return hashlib.new("md5", ":".join(data).encode("utf-8")).hexdigest()

    def build_ha1_ha2_digest(
        self, username: str, password: str, method: str, uri: str
    ) -> (str, str):
        # HA1 = MD5(username:realm:password)
        ha1 = self.build_md5_digest([username, self.realm, password])

        # HA2 = MD5(method:digestURI)
        ha2 = self.build_md5_digest([method, uri])

        return ha1, ha2

    def build_request_digest(
        self,
        request: DAVRequest,
        user: DAVUser,
        digest_auth_data: dict[str, str],
    ) -> str:
        ha1, ha2 = self.build_ha1_ha2_digest(
            username=user.username,
            password=user.password,
            method=request.method,
            uri=digest_auth_data.get("uri"),  # TODO!!!,
        )

        if digest_auth_data.get("qop") == "auth":
            # MD5(HA1:nonce:nonceCount:cnonce:qop:HA2)
            return self.build_md5_digest(
                [
                    ha1,
                    digest_auth_data.get("nonce"),
                    digest_auth_data.get("nc"),
                    digest_auth_data.get("cnonce"),
                    digest_auth_data.get("qop"),
                    ha2,
                ]
            )

        # MD5(HA1:nonce:HA2)
        return self.build_md5_digest(
            [
                ha1,
                digest_auth_data.get("nonce"),
                ha2,
            ]
        )


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
    realm = "ASGI-WebDAV"
    user_mapping: dict[str, DAVUser] = dict()  # username: password

    def __init__(self, config: Config):
        self.config = config

        for config_account in config.account_mapping:
            user = DAVUser(
                username=config_account.username,
                password=config_account.password,
                permissions=config_account.permissions,
                admin=config_account.admin,
            )

            self.user_mapping[config_account.username] = user
            logger.info("Register User: {}".format(user))

        self.basic_auth = HTTPBasicAuth(realm=self.realm)
        self.digest_auth = HTTPDigestAuth(realm=self.realm, secret=uuid4().hex)

    @staticmethod
    def _parser_password_string(password: str, flag_len: int) -> list[str] | None:
        if len(password) < flag_len + 1:
            return None

        separator_char = password[flag_len]
        return password.split(separator_char)

    def _check_hashlib_password(self, user: ConfigUser, password: str) -> bool:
        """
        password string format: "hashlib:algorithm:salt:hex-digest-string"
        hex-digest-string: hashlib.new(algorithm, b"{salt}:{password}").hexdigest()
        """
        pw_data = self._parser_password_string(user.password, 7)
        if len(pw_data) != 4:
            raise AuthFailedException(
                "Wrong password format in Config:{}".format(user.password)
            )

        # create hash sting
        try:
            hash_str = hashlib.new(
                pw_data[1], "{}:{}".format(pw_data[2], password).encode("utf-8")
            ).hexdigest()
        except ValueError as e:
            raise AuthFailedException(e)

        if hash_str == pw_data[3]:
            return True

        return False

    async def _check_ldap_password(self, user: ConfigUser, password) -> bool:
        """ "
        "ldap#1#ldaps:/your.domain.com#SIMPLE#uid=user-ldap,cn=users,dc=rexzhang,dc=myds,dc=me"
        """
        pw_data = self._parser_password_string(user.password, 4)
        if len(pw_data) != 5 or pw_data[1] != "1":
            raise AuthFailedException(
                "Wrong password format in Config:{}".format(user.password)
            )

        client = bonsai.LDAPClient(pw_data[2])
        client.set_credentials(pw_data[3], user=pw_data[4], password=password)
        try:
            conn = await client.connect(is_async=True)
            # result = await conn.search(
            #     base=ldap_username,
            #     scope=2,
            #     attrlist=["uid", "memberOf", "userPassword"],
            # )
            # if len(result) != 1:
            #     logger.warning("LDAP search failed")
            #     return False
            conn.close()

        except bonsai_exception.AuthenticationError:
            logger.info("Authentication Error, user:{}".format(user.username))
            return False
        except bonsai_exception.AuthMethodNotSupported:
            logger.warning(
                "LDAP auth method not supported, user:{}".format(user.username)
            )
            return False

        return True

    @staticmethod
    def _check_digest_password(user: ConfigUser, password: str) -> bool:
        """
        password string format: "digest:realm:HA1"
        HA1: hashlib.new("md5", b"{username}:{realm}:{password}").hexdigest()
        """
        return False

    async def _check_http_basic_auth_password(
        self, username: str, password: str
    ) -> bool:
        user = None
        for item in self.config.account_mapping:
            if item.username == username:
                user = item

        if user is None:
            return False

        if user.password.startswith("hashlib"):
            # hashlib
            if self._check_hashlib_password(user, password):
                return True
            else:
                return False

        elif user.password.startswith("ldap"):
            # LDAP
            if await self._check_ldap_password(user, password):
                return True
            else:
                return False

        elif user.password.startswith("digest"):
            # digest
            if self._check_digest_password(user, password):
                return True
            else:
                return False

        # RAW
        if password == user.password:
            return True

        return False

    async def pick_out_user(self, request: DAVRequest) -> (DAVUser | None, str):
        authorization_header = request.headers.get(b"authorization")
        if authorization_header is None:
            return None, "miss header: authorization"

        index = authorization_header.find(b" ")
        if index == -1:
            return None, "wrong header: authorization"

        auth_header_type = authorization_header[:index]
        auth_header_data = authorization_header[index + 1 :]

        # HTTP Basic Auth
        if self.basic_auth.is_credential(auth_header_type):
            request.authorization_method = "Basic"

            user = await self.basic_auth.get_user_from_cache(auth_header_data)
            if user is not None:
                return user, ""

            try:
                username, password = self.basic_auth.parser_auth_header_data(
                    auth_header_data
                )
            except AuthFailedException:
                return None, "no permission"  # TODO

            if not await self._check_http_basic_auth_password(username, password):
                return None, "no permission"  # TODO

            user = self.user_mapping.get(username)
            if user is None:
                return None, "no permission"  # TODO

            await self.basic_auth.update_user_to_cache(auth_header_data, user)
            return user, ""

        # HTTP Digest Auth
        if self.digest_auth.is_credential(auth_header_type):
            request.authorization_method = "Digest"

            digest_auth_data = self.digest_auth.authorization_str_parser_to_data(
                (authorization_header[7:].decode("utf-8"))
            )
            if len(DIGEST_AUTHORIZATION_PARAMS - set(digest_auth_data.keys())) > 0:
                return None, "no permission"

            user = self.user_mapping.get(digest_auth_data.get("username"))
            if user is None:
                return None, "no permission"

            expected_request_digest = self.digest_auth.build_request_digest(
                request=request,
                user=user,
                digest_auth_data=digest_auth_data,
            )
            request_digest = digest_auth_data.get("response")
            if expected_request_digest != request_digest:
                logger.debug(
                    f"expected_request_digest:{expected_request_digest},"
                    f" but request_digest:{request_digest}"
                )
                return None, "no permission"

            # https://datatracker.ietf.org/doc/html/rfc2617#page-15
            # macOS 11.4 finder supported
            #   WebDAVFS/3.0.0 (03008000) Darwin/20.5.0 (x86_64)
            request.authorization_info = (
                self.digest_auth.make_response_authentication_info_string(
                    request=request,
                    user=user,
                    digest_auth_data=digest_auth_data,
                )
            )
            return user, ""

        return None, "Unknown authentication method"

    def create_response_401(self, request: DAVRequest, message: str) -> DAVResponse:
        if self.config.http_digest_auth.enable:
            if self._match_user_agent(
                rule=self.config.http_digest_auth.disable_rule,
                user_agent=request.client_user_agent,
            ):
                enable_digest = False
            else:
                enable_digest = True

        else:
            if self._match_user_agent(
                rule=self.config.http_digest_auth.enable_rule,
                user_agent=request.client_user_agent,
            ):
                enable_digest = True
            else:
                enable_digest = False

        if enable_digest:
            challenge_string = self.digest_auth.make_auth_challenge_string()
            logger.debug("response Digest auth challenge")
        else:
            challenge_string = self.basic_auth.make_auth_challenge_string()
            logger.debug("response Basic auth challenge")

        return DAVResponse(
            status=401,
            content=MESSAGE_401_TEMPLATE.format(message).encode("utf-8"),
            headers={b"WWW-Authenticate": challenge_string},
        )

    @staticmethod
    def _match_user_agent(rule: str, user_agent: str) -> bool:
        if re.match(rule, user_agent) is None:
            return False

        return True

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

        return data
