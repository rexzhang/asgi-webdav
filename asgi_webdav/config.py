from typing import List, Optional
import json
from enum import Enum
from os import getenv
from pathlib import Path

from pydantic import BaseModel


class LoggingLevel(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


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


class Account(BaseModel):
    username: str
    password: str
    permissions: List[str]

    def __str__(self):
        return "{}, ***, {}".format(self.username, self.permissions)


class Config(BaseModel):
    # auth
    account_mapping: List[Account] = list()

    # provider
    provider_mapping: List[Provider] = list()

    # response
    display_dir_browser: bool = True

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

    def set_default_value(self):
        if len(self.account_mapping) == 0:
            self.account_mapping.append(
                Account(username="username", password="password", permissions=["+"])
            )

        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(Provider(prefix="/", uri="file:///data"))


def create_config_from_file(config_path: str = "/data") -> Config:
    """config data folder default value: /data"""
    config_path = getenv("WEBDAV_DATA", config_path)

    # create/update config value from file
    config_path = Path(config_path).joinpath("webdav.json")
    try:
        obj = Config.parse_file(config_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(
            "WARNING: load config value from file[{}] failed, {}".format(config_path, e)
        )
        obj = Config()

    obj.update_from_env()
    obj.set_default_value()
    return obj


def create_config_from_obj(obj: dict) -> Config:
    obj = Config.parse_obj(obj)

    obj.update_from_env()
    obj.set_default_value()
    return obj
