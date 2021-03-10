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
    prefix: str  # prefix 需要以 / 结束
    uri: str  # file:///home/user_a/webdav/prefix
    readonly: bool = False  # TODO impl


class Config(BaseModel):
    logging_level: LoggingLevel = LoggingLevel.INFO
    username: str = 'username'
    password: str = 'password'

    provider_mapping: List[ProviderMapping] = list()

    sentry_dsn: Optional[str] = None

    def update_from_file_and_env(self, config_path: str = '/data'):
        """config data folder default value: /data"""
        config_path = getenv('WEBDAV_DATA', config_path)

        # update config value from file
        try:
            self.parse_file(
                Path(config_path).joinpath('webdav.json')
            )
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        if len(self.provider_mapping) == 0:
            self.provider_mapping.append(
                ProviderMapping(prefix='/', uri='file:///data')
            )

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
