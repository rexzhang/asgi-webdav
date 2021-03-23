from typing import List, Optional
import json
from enum import Enum
from os import getenv
from pathlib import Path

from pydantic import BaseModel


class LoggingLevel(Enum):
    CRITICAL = 'CRITICAL'
    ERROR = 'ERROR'
    WARNING = 'WARNING'
    INFO = 'INFO'
    DEBUG = 'DEBUG'


class ProviderMapping(BaseModel):
    prefix: str  # '/', '/a/b/c', '/a/b/c/'
    uri: str  # file:///home/user_a/webdav/prefix
    readonly: bool = False  # TODO impl


class Config(BaseModel):
    logging_level: LoggingLevel = LoggingLevel.INFO
    username: str = 'username'
    password: str = 'password'

    provider_mapping: List[ProviderMapping] = list()

    sentry_dsn: Optional[str] = None

    def set_default_value(self):
        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(
                ProviderMapping(prefix='/', uri='file:///data')
            )

    def update_from_env(self):
        # update config value from env
        logging_level = getenv('LOGGING_LEVEL')
        if logging_level:
            self.logging_level = LoggingLevel(logging_level)

        username = getenv('USERNAME')
        if username:
            self.username = username
        password = getenv('PASSWORD')
        if password:
            self.password = password

        sentry_dsn = getenv('SENTRY_DSN')
        if sentry_dsn:
            self.sentry_dsn = sentry_dsn


def create_config_from_file(config_path: str = '/data') -> Config:
    """config data folder default value: /data"""
    config_path = getenv('WEBDAV_DATA', config_path)

    # create/update config value from file
    config_path = Path(config_path).joinpath('webdav.json')
    try:
        obj = Config.parse_file(config_path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print('WARNING: load config value from file[{}] failed, {}'.format(
            config_path, e
        ))
        obj = Config()

    obj.set_default_value()
    obj.update_from_env()
    return obj


def create_config_from_obj(obj: dict) -> Config:
    obj = Config.parse_obj(obj)
    obj.set_default_value()
    obj.update_from_env()
    return obj
