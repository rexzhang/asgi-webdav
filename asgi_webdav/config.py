import json
from enum import Enum
from logging import getLogger
from os import getenv

from pydantic import BaseModel

from asgi_webdav.constants import (
    DEFAULT_FILENAME_CONTENT_TYPE_MAPPING,
    DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING,
    AppEntryParameters,
    DAVCompressLevel,
)
from asgi_webdav.exception import WebDAVException

logger = getLogger(__name__)


class User(BaseModel):
    username: str
    password: str
    permissions: list[str]
    admin: bool = False


class HTTPDigestAuth(BaseModel):
    enable: bool = False
    enable_rule: str = ""  # Valid when "enable" is false
    disable_rule: str = "neon/"  # Valid when "enable" is true
    # TODO Compatible with neon


class Provider(BaseModel):
    """
    Home Dir:
        home_dir: True
        prefix: "/~", "/home"
        uri: file:///home/all_user/home

    Shared Dir:
        home_dir: False
        prefix: '/', '/a/b/c', '/a/b/c/'
        uri: file:///home/user_a/webdav/prefix
    """

    prefix: str
    uri: str
    home_dir: bool = False
    readonly: bool = False  # TODO impl


class GuessTypeExtension(BaseModel):
    enable: bool = True
    enable_default_mapping: bool = True

    filename_mapping: dict = dict()
    suffix_mapping: dict = dict()


class TextFileCharsetDetect(BaseModel):
    enable: bool = False
    default: str = "utf-8"


class Compression(BaseModel):
    enable_gzip: bool = True
    enable_brotli: bool = True
    level: DAVCompressLevel = DAVCompressLevel.RECOMMEND

    content_type_user_rule: str = ""


class CORS(BaseModel):
    enable: bool = False
    allow_url_regex: str | None = None
    allow_origins: list[str] = ()
    allow_origin_regex: str | None = None
    allow_methods: list[str] = ("GET",)
    allow_headers: list[str] = ()
    allow_credentials: bool = False
    expose_headers: list[str] = ()
    preflight_max_age: int = 600


class HideFileInDir(BaseModel):
    enable: bool = True
    enable_default_rules: bool = True
    user_rules: dict[str, str] = dict()


class LoggingLevel(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class Config(BaseModel):
    # auth
    account_mapping: list[User] = list()  # TODO => user_mapping ?
    http_digest_auth: HTTPDigestAuth = HTTPDigestAuth()

    # provider
    provider_mapping: list[Provider] = list()  # TODO => prefix_mapping ?

    # rules process
    hide_file_in_dir: HideFileInDir = HideFileInDir()
    guess_type_extension: GuessTypeExtension = GuessTypeExtension()
    text_file_charset_detect: TextFileCharsetDetect = TextFileCharsetDetect()

    # response
    compression: Compression = Compression()
    cors: CORS = CORS()
    enable_dir_browser: bool = True

    # other
    logging_level: LoggingLevel = LoggingLevel.INFO
    sentry_dsn: str | None = None

    def update_from_app_args_and_env_and_default_value(self, aep: AppEntryParameters):
        """
        CLI Args > Environment Variable > Configuration File > Default Value
        """

        # auth
        if aep.admin_user is not None:
            username = aep.admin_user[0]
            password = aep.admin_user[1]
        elif getenv("WEBDAV_PASSWORD") is not None:
            username = getenv("WEBDAV_USERNAME")
            password = getenv("WEBDAV_PASSWORD")
        else:
            username = None
            password = None

        if username is not None:
            user_id = None
            for index in range(len(self.account_mapping)):
                if self.account_mapping[index].username == username:
                    user_id = index
                    break

            if user_id is None:
                account = User(username=username, password=password, permissions=["+"])

                self.account_mapping.append(account)

            else:
                account = self.account_mapping[user_id]
                account.username = username
                account.password = password

                self.account_mapping[user_id] = account

        # auth - default
        if len(self.account_mapping) == 0:
            self.account_mapping.append(
                User(username="username", password="password", permissions=["+"])
            )

        # provider - CLI
        if aep.root_path is not None:
            root_path_index = None
            for index in range(len(self.provider_mapping)):
                if self.provider_mapping[index].prefix == "/":
                    root_path_index = index
                    break

            root_path_uri = f"file://{aep.root_path}"
            if root_path_index is None:
                self.provider_mapping.append(Provider(prefix="/", uri=root_path_uri))
            else:
                self.provider_mapping[root_path_index].uri = root_path_uri

        # provider - default
        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(Provider(prefix="/", uri="file:///data"))

        # response - default
        if self.guess_type_extension.enable_default_mapping:
            new_mapping = dict()
            new_mapping.update(DEFAULT_FILENAME_CONTENT_TYPE_MAPPING)
            new_mapping.update(self.guess_type_extension.filename_mapping)
            self.guess_type_extension.filename_mapping = new_mapping

            new_mapping = dict()
            new_mapping.update(DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING)
            new_mapping.update(self.guess_type_extension.suffix_mapping)
            self.guess_type_extension.suffix_mapping = new_mapping

        # other - env
        logging_level = getenv("WEBDAV_LOGGING_LEVEL")
        if logging_level:
            self.logging_level = LoggingLevel(logging_level)

        sentry_dsn = getenv("WEBDAV_SENTRY_DSN")
        if sentry_dsn:
            self.sentry_dsn = sentry_dsn


_config: Config | None = None


def get_config() -> Config:
    global _config

    if _config is None:
        raise WebDAVException("Please init config object first!")

    return _config


def init_config_object():
    global _config
    if _config is None:
        _config = Config()


def init_config_from_file(config_file: str) -> Config:
    global _config
    if _config is None:
        _config = Config()

    try:
        _config = _config.parse_file(config_file)

    except (FileNotFoundError, json.JSONDecodeError) as e:
        message = f"Load config value from file[{config_file}] failed!"
        logger.warning(message)
        logger.warning(e)

    logger.info(f"Load config value from config file:{config_file}")
    return _config


def init_config_from_obj(obj: dict) -> Config:
    global _config
    if _config is None:
        _config = Config()

    logger.debug("Load config value from python object")
    _config = _config.parse_obj(obj)

    return _config
