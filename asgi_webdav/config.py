from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from dataclass_wizard import EnvWizard, JSONPyWizard

from asgi_webdav.cache import DAVCacheType
from asgi_webdav.constants import (
    DEFAULT_FILENAME_CONTENT_TYPE_MAPPING,
    DEFAULT_HTTP_BASIC_AUTH_CACHE_TIMEOUT,
    DEFAULT_PASSWORD,
    DEFAULT_PASSWORD_ANONYMOUS,
    DEFAULT_PERMISSIONS,
    DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING,
    DEFAULT_USERNAME,
    DEFAULT_USERNAME_ANONYMOUS,
    AppEntryParameters,
    DAVCompressLevel,
    LoggingLevel,
)

logger = getLogger(__name__)


class EnvConfig(EnvWizard):
    class _(EnvWizard.Meta):
        env_prefix = "WEBDAV_"
        env_file = True

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
class Anonymous:
    enable: bool = False
    user: User = field(
        default_factory=lambda: User(
            DEFAULT_USERNAME_ANONYMOUS, DEFAULT_PASSWORD_ANONYMOUS, DEFAULT_PERMISSIONS
        )
    )
    allow_missing_auth_header: bool = True


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
    type: str = ""

    home_dir: bool = False
    read_only: bool = False
    ignore_property_extra: bool = True


@dataclass
class GuessTypeExtension:
    enable: bool = True
    enable_default_mapping: bool = True

    filename_mapping: dict[str, str] = field(default_factory=dict)
    suffix_mapping: dict[str, str] = field(default_factory=dict)


@dataclass
class TextFileCharsetDetect:
    enable: bool = False
    default: str = "utf-8"


@dataclass
class Compression:
    enable: bool = True
    enable_zstd: bool = True
    enable_deflate: bool = True
    enable_gzip: bool = True

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


@dataclass
class Logging:
    enable: bool = True
    level: LoggingLevel = LoggingLevel.INFO
    display_datetime: bool = True
    use_colors: bool = True
    access_log: bool = True  # TODO Impl


@dataclass
class Config(JSONPyWizard):
    # auth
    account_mapping: list[User] = field(default_factory=list)

    anonymous: Anonymous = field(default_factory=Anonymous)

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

    def _update_from_env_config(self, env_config: EnvConfig) -> None:
        # account_mapping
        if env_config.username is not None and env_config.password is not None:
            self.account_mapping.insert(
                0,
                User(
                    username=env_config.username,
                    password=env_config.password,
                    permissions=DEFAULT_PERMISSIONS,
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

    def _update_from_app_args(self, aep: AppEntryParameters) -> None:
        # account_mapping
        if aep.admin_user is not None:
            self.account_mapping.insert(
                0,
                User(
                    username=aep.admin_user[0],
                    password=aep.admin_user[1],
                    permissions=DEFAULT_PERMISSIONS,
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

    def _complete_config(self) -> None:
        # auth - anonymous
        if self.anonymous.enable:
            self.account_mapping.append(self.anonymous.user)
            logger.info(
                f"Enable anonymous user: {self.anonymous.user.username}, permissions: {self.anonymous.user.permissions}, admin: {self.anonymous.user.admin}"
            )

        # auth - default(admin) user
        if len(self.account_mapping) == 0:
            self.account_mapping.append(
                User(
                    username=DEFAULT_USERNAME,
                    password=DEFAULT_PASSWORD,
                    permissions=DEFAULT_PERMISSIONS,
                    admin=True,
                )
            )
            logger.warning(
                f"Add defalut(admin) user: {DEFAULT_USERNAME}, password:{DEFAULT_PASSWORD}, permissions: {DEFAULT_PERMISSIONS}"
            )

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

    def update_from_app_args_and_env_and_default_value(
        self, aep: AppEntryParameters
    ) -> None:
        """
        CLI Args > Environment Variable > Configuration File > Default Value
        """
        self._update_from_env_config(EnvConfig())
        self._update_from_app_args(aep)
        self._complete_config()


def generate_config_from_dict(
    data: dict[str, Any], complete_config: bool = False
) -> Config:
    config = Config.from_dict(data)
    if complete_config:
        config._complete_config()

    return config


def generate_config_from_file(
    file: Path | str, complete_config: bool = False
) -> Config | None:
    load_func: Callable[[Any], Any]
    if not isinstance(file, Path):
        file = Path(file)

    match file.suffix:
        case ".json":
            load_func = json.load
        case ".toml":
            load_func = tomllib.load
        case _:
            message = f"Unsupported config file type: {file.suffix}"
            logger.error(message)
            return None

    try:
        with open(file, "rb") as f:
            data = load_func(f)

    except FileNotFoundError as e:
        logger.error(f"Can not open config file[{file}]!, {e}")
        return None

    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as e:
        message = f"Load config from file[{file}] failed!"
        logger.error(message)
        logger.error(e)
        return None

    config = generate_config_from_dict(data, complete_config)
    logger.info(f"Load config from file: [{file}] success!")
    return config


def generate_config_from_file_with_multi_suffix(
    file: Path | str, complete_config: bool = False
) -> Config | None:
    """help users in switching from .json to .toml configuration files."""

    if not isinstance(file, Path):
        file = Path(file)

    config = generate_config_from_file(file, complete_config)
    if config is not None:
        return config

    # try other suffix
    stem = file.stem
    suffix = file.suffix

    suffixs = {".json", ".toml"}
    try:
        suffixs.remove(suffix)
    except KeyError as e:
        logger.warning(f"Wrong file extension: {suffix}, {e}")

    for suffix in suffixs:
        file = file.parent.joinpath(f"{stem}{suffix}")
        logger.warning(f"Try load config file: {file}!")

        config = generate_config_from_file(file, complete_config)
        if config is None:
            logger.warning(f"Can not found config file: {file}!")
        else:
            # loaded
            return config

    # all failed
    return None


_config: Config = Config()


def get_global_config() -> Config:
    return _config


def reinit_global_config(config: Config | None = None) -> None:
    global _config

    if config is None:
        config = Config()

    _config = config
