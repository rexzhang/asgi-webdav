import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from logging import getLogger
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from dataclass_wizard import EnvWizard, JSONWizard

from asgi_webdav.cache import DAVCacheType
from asgi_webdav.constants import (
    DEFAULT_FILENAME_CONTENT_TYPE_MAPPING,
    DEFAULT_HTTP_BASIC_AUTH_CACHE_TIMEOUT,
    DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING,
    AppEntryParameters,
    DAVCompressLevel,
)

logger = getLogger(__name__)


class EnvConfig(EnvWizard):
    class _(EnvWizard.Meta):
        env_prefix = "WEBDAV_"

    username: str | None = None
    password: str | None = None

    logging_level: str | None = None
    sentry_dsn: str | None = None


@dataclass
class User:
    username: str
    password: str
    permissions: list[str]

    admin: bool = False


@dataclass
class HTTPBasicAuth:
    # enable: bool = True
    cache_type: DAVCacheType = DAVCacheType.MEMORY
    cache_timeout: int = DEFAULT_HTTP_BASIC_AUTH_CACHE_TIMEOUT  # x second


@dataclass
class HTTPDigestAuth:
    enable: bool = False
    enable_rule: str = ""  # Valid when "enable" is false
    disable_rule: str = "neon/"  # Valid when "enable" is true
    # TODO Compatible with neon


@dataclass
class Provider:
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
    read_only: bool = False
    ignore_property_extra: bool = True


@dataclass
class GuessTypeExtension:
    enable: bool = True
    enable_default_mapping: bool = True

    filename_mapping: dict = field(default_factory=dict)
    suffix_mapping: dict = field(default_factory=dict)


@dataclass
class TextFileCharsetDetect:
    enable: bool = False
    default: str = "utf-8"


@dataclass
class Compression:
    enable: bool = True
    enable_gzip: bool = True
    enable_brotli: bool = True
    level: DAVCompressLevel = DAVCompressLevel.RECOMMEND

    content_type_user_rule: str = ""


@dataclass
class CORS:
    enable: bool = False
    allow_url_regex: str | None = None
    allow_origins: list[str] = field(default_factory=list)
    allow_origin_regex: str | None = None
    allow_methods: list[str] = field(default_factory=lambda: ["GET"])
    allow_headers: list[str] = field(default_factory=list)
    allow_credentials: bool = False
    expose_headers: list[str] = field(default_factory=list)
    preflight_max_age: int = 600


@dataclass
class HideFileInDir:
    # 是否启用隐藏文件功能
    enable: bool = True
    enable_default_rules: bool = True
    user_rules: dict[str, str] = field(default_factory=dict)


class LoggingLevel(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


@dataclass
class Logging:
    enable: bool = True
    level: LoggingLevel = LoggingLevel.INFO
    display_datetime: bool = True
    use_colors: bool = True
    access_log: bool = True  # TODO Impl


@dataclass
class Config(JSONWizard):
    # auth
    account_mapping: list[User] = field(default_factory=list)
    http_basic_auth: HTTPBasicAuth = field(default_factory=HTTPBasicAuth)
    http_digest_auth: HTTPDigestAuth = field(default_factory=HTTPDigestAuth)

    # provider
    provider_mapping: list[Provider] = field(default_factory=list)

    # rules process
    hide_file_in_dir: HideFileInDir = field(default_factory=HideFileInDir)
    guess_type_extension: GuessTypeExtension = field(default_factory=GuessTypeExtension)
    text_file_charset_detect: TextFileCharsetDetect = field(
        default_factory=TextFileCharsetDetect
    )

    # response
    compression: Compression = field(default_factory=Compression)
    cors: CORS = field(default_factory=CORS)
    enable_dir_browser: bool = True

    # other
    logging: Logging = field(default_factory=Logging)
    sentry_dsn: str | None = None
    cache_expiration: int = DEFAULT_HTTP_BASIC_AUTH_CACHE_TIMEOUT

    def _update_from_env_config(self):
        env_config = EnvConfig()

        # account_mapping
        if env_config.username is not None and env_config.password is not None:
            self.account_mapping.insert(
                0,
                User(
                    username=env_config.username,
                    password=env_config.password,
                    permissions=["+"],
                ),
            )
            logger.info(f"Add user from ENV: {self.account_mapping[0].username}")

        # other
        if env_config.logging_level is not None:
            try:
                self.logging.level = LoggingLevel(env_config.logging_level)
                logger.info(f"Set logging level from ENV to {self.logging.level}")
            except ValueError:
                logger.error(f"Invalid logging level: {env_config.logging_level}")

        if env_config.sentry_dsn is not None:
            self.sentry_dsn = env_config.sentry_dsn
            logger.info(f"Set Sentry DSN from ENV to {self.sentry_dsn}")

    def _update_from_app_args(self, aep: AppEntryParameters):
        # account_mapping
        if aep.admin_user is not None:
            self.account_mapping.insert(
                0,
                User(
                    username=aep.admin_user[0],
                    password=aep.admin_user[1],
                    permissions=["+"],
                    admin=True,
                ),
            )
            logger.info(f"Add user from ENV: {self.account_mapping[0].username}")

        # provider_mapping
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

    def _fix_config(self):
        # account_mapping
        if len(self.account_mapping) == 0:
            self.account_mapping.append(
                User(username="username", password="password", permissions=["+"])
            )
            logger.warning("Add defalut user: username/password")

        if len(self.account_mapping) == 1:
            self.account_mapping[0].admin = True
            logger.warning("Set the only account as admin")

        # provider - default
        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(Provider(prefix="/", uri="file:///data"))
            logger.warning("Add defalut provider: file:///data")

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

    def update_from_app_args_and_env_and_default_value(self, aep: AppEntryParameters):
        """
        CLI Args > Environment Variable > Configuration File > Default Value
        """
        self._update_from_env_config()
        self._update_from_app_args(aep)
        self._fix_config()


_config: Config = Config()


def get_config() -> Config:
    return _config


def reinit_config_from_dict(data: dict) -> Config:
    global _config

    logger.debug("Load config value from python object(dict)")
    _config = Config.from_dict(data)

    return _config


def reinit_config_from_file(file_name: str) -> bool:
    file = Path(file_name)
    match file.suffix:
        case ".json":
            load_func = json.load
        case ".toml":
            load_func = tomllib.load
        case _:
            message = f"Unsupported config file type: {file.suffix}"
            logger.error(message)
            return False

    try:
        with open(file, "rb") as f:
            data = load_func(f)

    except FileNotFoundError as e:
        message = f"Can not open config file[{file}]!"
        logger.error(message)
        logger.error(e)
        return False

    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as e:
        message = f"Load config from file[{file}] failed!"
        logger.error(message)
        logger.error(e)
        return False

    global _config
    _config = reinit_config_from_dict(data)

    return True
