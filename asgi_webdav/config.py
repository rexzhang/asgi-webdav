from typing import Optional
import json
from enum import Enum
from os import getenv
from logging import getLogger

from pydantic import BaseModel

from asgi_webdav.constants import (
    DEFAULT_FILENAME_CONTENT_TYPE_MAPPING,
    DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING,
    DAVCompressLevel,
)


logger = getLogger(__name__)


class Account(BaseModel):
    username: str
    password: str
    permissions: list[str]
    admin: bool = False


class HTTPDigestAuth(BaseModel):
    enable: bool = False
    disable_rule: str = "neon/"


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

    user_content_type_rule: str = ""


class DirBrowser(BaseModel):
    enable: bool = True
    enable_macos_ignore_rules: bool = True
    enable_windows_ignore_rules: bool = True
    enable_synology_ignore_rules: bool = True

    user_ignore_rule: str = str()


class LoggingLevel(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class Config(BaseModel):
    # auth
    account_mapping: list[Account] = list()
    http_digest_auth: HTTPDigestAuth = HTTPDigestAuth()

    # provider
    provider_mapping: list[Provider] = list()

    # process
    guess_type_extension: GuessTypeExtension = GuessTypeExtension()
    text_file_charset_detect: TextFileCharsetDetect = TextFileCharsetDetect()

    # response
    compression: Compression = Compression()
    dir_browser: DirBrowser = DirBrowser()

    # other
    logging_level: LoggingLevel = LoggingLevel.INFO
    sentry_dsn: Optional[str] = None

    def update_from_env(self):
        # update config value from env
        username = getenv("WEBDAV_USERNAME")
        password = getenv("WEBDAV_PASSWORD")
        if username and password:
            account_id = None
            for index in range(len(self.account_mapping)):
                if self.account_mapping[index].username == username:
                    account_id = index
                    break

            if account_id is None:
                account = Account(
                    username=username, password=password, permissions=["+"]
                )

                self.account_mapping.append(account)

            else:
                account = self.account_mapping[account_id]
                account.username = username
                account.password = password

                self.account_mapping[account_id] = account

        logging_level = getenv("WEBDAV_LOGGING_LEVEL")
        if logging_level:
            self.logging_level = LoggingLevel(logging_level)

        sentry_dsn = getenv("WEBDAV_SENTRY_DSN")
        if sentry_dsn:
            self.sentry_dsn = sentry_dsn

        return

    def set_default_value(self):
        if len(self.account_mapping) == 0:
            self.account_mapping.append(
                Account(username="username", password="password", permissions=["+"])
            )

        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(Provider(prefix="/", uri="file:///data"))

        if self.guess_type_extension.enable_default_mapping:
            new_mapping = dict()
            new_mapping.update(DEFAULT_FILENAME_CONTENT_TYPE_MAPPING)
            new_mapping.update(self.guess_type_extension.filename_mapping)
            self.guess_type_extension.filename_mapping = new_mapping

            new_mapping = dict()
            new_mapping.update(DEFAULT_SUFFIX_CONTENT_TYPE_MAPPING)
            new_mapping.update(self.guess_type_extension.suffix_mapping)
            self.guess_type_extension.suffix_mapping = new_mapping

        return


config = Config()


def get_config() -> Config:
    global config
    return config


def update_config_from_file(config_file: str) -> Config:
    global config
    try:
        config = config.parse_file(config_file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        message = "Load config value from file[{}] failed!".format(config_file)
        logger.warning(message)
        logger.warning(e)

    config.update_from_env()
    config.set_default_value()
    return config


def update_config_from_obj(obj: dict) -> Config:
    global config
    config = config.parse_obj(obj)
    config.update_from_env()
    config.set_default_value()
    return config
