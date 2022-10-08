import asyncio
import binascii
import hashlib
import re
from base64 import b64decode
from enum import IntEnum
from logging import getLogger
from uuid import uuid4

try:
    import bonsai
    from bonsai import errors as bonsai_exception
except ImportError:
    bonsai = None
    bonsai_exception = None

from asgi_webdav.config import Config
from asgi_webdav.constants import DAVUser
from asgi_webdav.exception import AuthFailedException
from asgi_webdav.request import DAVRequest
from asgi_webdav.response import DAVResponse

logger = getLogger(__name__)

"""
Ref:
- https://en.wikipedia.org/wiki/Basic_access_authentication
- https://en.wikipedia.org/wiki/Digest_access_authentication
- https://datatracker.ietf.org/doc/html/rfc2617
    - HTTP Authentication: Basic and Digest Access Authentication
- https://datatracker.ietf.org/doc/html/rfc7616
    - HTTP Digest Access Authentication
- https://datatracker.ietf.org/doc/html/rfc7617
    - The 'Basic' HTTP Authentication Scheme
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Authentication
- https://developer.mozilla.org/zh-CN/docs/Web/HTTP/Headers/Digest

- https://github.com/dimagi/python-digest/blob/master/python_digest/__init__.py
- https://github.com/psf/requests/blob/master/requests/auth.py
- https://gist.github.com/dayflower/5828503

LDAP
- https://www.openldap.org/doc/admin24/security.html
"""


def _md5(data: str) -> str:
    return hashlib.new(
        "md5", data.encode("utf-8")  # lgtm [py/weak-sensitive-data-hashing]
    ).hexdigest()


class DAVPasswordType(IntEnum):
    INVALID = 0
    RAW = 1
    HASHLIB = 2
    DIGEST = 3
    LDAP = 4


DAV_PASSWORD_TYPE_MAPPING = {
    "hashlib": (4, DAVPasswordType.HASHLIB),
    "digest": (3, DAVPasswordType.DIGEST),
    "ldap": (5, DAVPasswordType.LDAP),
}


class DAVPassword:
    password: str

    type: DAVPasswordType
    data: list[str] | None = None
    message: str | None = None

    def _parser_password_string(self) -> (DAVPasswordType, list[str]):
        m = re.match(r"^<(?P<sign>\w+)>(?P<split_char>[:#$&|])", self.password)
        if m is None:
            self.type = DAVPasswordType.RAW
            return

        sign = m.group("sign")
        split_char = m.group("split_char")
        if sign not in DAV_PASSWORD_TYPE_MAPPING:
            self.type = DAVPasswordType.INVALID
            self.message = "Invalid password, cannot match split char"
            return

        data = self.password.split(split_char)
        if len(data) != DAV_PASSWORD_TYPE_MAPPING[sign][0]:
            self.type = DAVPasswordType.INVALID
            self.message = "Invalid password, cannot match password type"

            logger.error(self.message)
            return

        self.type = DAV_PASSWORD_TYPE_MAPPING[sign][1]
        self.data = data
        return

    def __init__(self, password: str):
        self.password = password

        self._parser_password_string()

    def check_hashlib_password(self, password: str) -> (bool, str | None):
        """
        password string format: "<hashlib>:algorithm:salt:hex-digest-string"
        hex-digest-string: hashlib.new(algorithm, b"{salt}:{password}").hexdigest()
        """
        try:
            hash_str = hashlib.new(
                self.data[1],
                f"{self.data[2]}:{password}".encode("utf-8"),
            ).hexdigest()
        except ValueError as e:
            return False, str(e)

        if hash_str == self.data[3]:
            return True, None

        return False, None

    async def check_ldap_password(self, password: str) -> (bool, str | None):
        """ "
        "<ldap>#1#ldaps:/your.domain.com#SIMPLE#uid=user-ldap,cn=users,dc=rexzhang,dc=myds,dc=me"
        """
        if bonsai is None:
            return False, "Please install LDAP module: pip install -U ASGIWebDAV[ldap]"

        if self.data[1] != "1":
            return False, "Wrong password format in Config"

        client = bonsai.LDAPClient(self.data[2])
        client.set_credentials(self.data[3], user=self.data[4], password=password)
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
            return False, "LDAP Authentication Error"
        except bonsai_exception.AuthMethodNotSupported:
            return False, "LDAP auth method not supported"

        return True, None

    def check_digest_password(self, username: str, password: str) -> (bool, str | None):
        """
        password string format: "<digest>:{realm}:{HA1}"
        HA1: hashlib.new("md5", b"{username}:{realm}:{password}").hexdigest()
        """
        if self.data[2] == _md5(":".join([username, self.data[1], password])):
            return True, None

        return False, None

    def __repr__(self):
        return f"{self.type}|{self.data}"


class HTTPAuthAbc:
    realm: str

    def __init__(self, realm: str):
        self.realm = realm

    @staticmethod
    def is_credential(authorization_header: bytes) -> bool:  # pragma: no cover
        raise NotImplementedError

    def make_auth_challenge_string(self) -> bytes:  # pragma: no cover
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
        return f'Basic realm="{self.realm}"'.encode("utf-8")

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
            data = b64decode(auth_header_data).decode("utf-8")
        except binascii.Error:
            raise AuthFailedException()

        index = data.find(":")
        if index == -1:
            raise AuthFailedException()

        return data[:index], data[index + 1 :]

    @staticmethod
    async def check_password(user: DAVUser, password: str) -> bool:
        pw_obj = DAVPassword(user.password)

        match pw_obj.type:
            case DAVPasswordType.RAW:
                if password == user.password:
                    return True

                valid, message = False, None

            case DAVPasswordType.HASHLIB:
                valid, message = pw_obj.check_hashlib_password(password)

            case DAVPasswordType.DIGEST:
                valid, message = pw_obj.check_digest_password(user.username, password)

            case DAVPasswordType.LDAP:
                valid, message = await pw_obj.check_ldap_password(password)

            case _:
                valid, message = False, pw_obj.message

        if valid:
            return True

        if message is None:
            message = f"Password verification failed, username:{user.username}"
            logger.debug(message)  # TODO debug?info? config in file?

        else:
            logger.error(f"{message}, , username:{user.username}")

        return False


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
        ha1 = self.build_ha1_digest(user)
        ha2 = self.build_ha2_digest(
            method=request.method, uri=digest_auth_data.get("uri")
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
        return _md5(f"{uuid4().hex}{self.secret}")

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
                logger.error(f"parser:{value} failed, ", e)

        logger.debug(f"Digest string data:{data}")
        return data

    @staticmethod
    def authorization_string_build_from_data(data: dict[str, str]) -> str:
        return ", ".join(['{}="{}"'.format(k, v) for (k, v) in data.items()])

    @staticmethod
    def build_md5_digest(data: list[str]) -> str:
        return _md5(":".join(data))

    def build_ha1_digest(self, user: DAVUser) -> str:
        """
        HA1 = MD5(username:realm:password)
        """
        pw_obj = DAVPassword(user.password)
        match pw_obj.type:
            case DAVPasswordType.RAW:
                return self.build_md5_digest([user.username, self.realm, user.password])

            case DAVPasswordType.DIGEST:
                return pw_obj.data[2]

            case _:
                pass

        logger.error(f"{pw_obj.message}, , username:{user.username}")
        return ""

    def build_ha2_digest(self, method: str, uri: str) -> str:
        """
        HA2 = MD5(method:digestURI)
        """
        return self.build_md5_digest([method, uri])

    def build_request_digest(
        self,
        request: DAVRequest,
        user: DAVUser,
        digest_auth_data: dict[str, str],
    ) -> str:
        ha1 = self.build_ha1_digest(user)
        ha2 = self.build_ha2_digest(
            method=request.method, uri=digest_auth_data.get("uri")
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
    user_mapping: dict[str, DAVUser] = dict()

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
            logger.info(f"Register User: {user}")

        self.http_basic_auth = HTTPBasicAuth(realm=self.realm)
        self.http_digest_auth = HTTPDigestAuth(realm=self.realm, secret=uuid4().hex)

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
        if self.http_basic_auth.is_credential(auth_header_type):
            request.authorization_method = "Basic"

            user = await self.http_basic_auth.get_user_from_cache(auth_header_data)
            if user is not None:
                return user, ""

            try:
                (
                    username,
                    request_password,
                ) = self.http_basic_auth.parser_auth_header_data(auth_header_data)
            except AuthFailedException:
                return None, "no permission"  # TODO

            user = self.user_mapping.get(username)
            if user is None:
                return None, "no permission"  # TODO

            if not await self.http_basic_auth.check_password(user, request_password):
                return None, "no permission"  # TODO

            await self.http_basic_auth.update_user_to_cache(auth_header_data, user)
            return user, ""

        # HTTP Digest Auth
        if self.http_digest_auth.is_credential(auth_header_type):
            request.authorization_method = "Digest"

            digest_auth_data = self.http_digest_auth.authorization_str_parser_to_data(
                authorization_header[7:].decode("utf-8")
            )
            if len(DIGEST_AUTHORIZATION_PARAMS - set(digest_auth_data.keys())) > 0:
                return None, "no permission"

            user = self.user_mapping.get(digest_auth_data.get("username"))
            if user is None:
                return None, "no permission"

            expected_request_digest = self.http_digest_auth.build_request_digest(
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
                self.http_digest_auth.make_response_authentication_info_string(
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
            challenge_string = self.http_digest_auth.make_auth_challenge_string()
            logger.debug("response Digest auth challenge")
        else:
            challenge_string = self.http_basic_auth.make_auth_challenge_string()
            logger.debug("response Basic auth challenge")

        return DAVResponse(
            status=401,
            content=MESSAGE_401_TEMPLATE.format(message).encode("utf-8"),
            headers={b"WWW-Authenticate": challenge_string},
        )

    @staticmethod
    def _match_user_agent(rule: str, user_agent: str) -> bool:
        if rule == "":
            return False

        if re.search(rule, user_agent) is None:
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
