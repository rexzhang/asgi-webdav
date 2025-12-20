import pytest

from asgi_webdav.config import (
    Config,
    LoggingLevel,
    generate_config_from_dict,
    generate_config_from_file,
    generate_config_from_file_with_multi_suffix,
    get_config,
    reinit_global_config,
)
from asgi_webdav.constants import (
    DEFAULT_PASSWORD_ANONYMOUS,
    DEFAULT_PERMISSIONS,
    DEFAULT_USERNAME_ANONYMOUS,
)

from .testkit_common import get_project_root_path

EXAMPLE_CONFIG_ROOT_PATH = get_project_root_path().joinpath("examples/config")

TEST_PERMISSIONS = ["+^/$"]


@pytest.fixture
def default_config():
    config = Config()

    yield config

    pass


def test_defalut_config(default_config):
    config = default_config
    assert config.anonymous.enable is False
    assert config.anonymous.user.username == DEFAULT_USERNAME_ANONYMOUS
    assert config.anonymous.user.password == DEFAULT_PASSWORD_ANONYMOUS
    assert config.anonymous.user.permissions == DEFAULT_PERMISSIONS

    assert config.logging.enable is True
    assert config.logging.level == LoggingLevel.INFO


def test_generate_config_from_dict():
    config = generate_config_from_dict(
        {
            "anonymous": {
                "enable": True,
                "user": {
                    "username": "test_user",
                    "password": "test_password",
                    "permissions": TEST_PERMISSIONS,
                },
            },
            "logging": {
                "enable": False,
                "level": "DEBUG",
            },
        }
    )

    assert config.anonymous.enable is True
    assert config.anonymous.user.username == "test_user"
    assert config.anonymous.user.password == "test_password"
    assert config.anonymous.user.permissions == TEST_PERMISSIONS


def test_generate_config_from_file():

    config = generate_config_from_file(
        EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-limited-permission.toml")
    )

    assert config.anonymous.enable is True
    assert config.anonymous.user.permissions == TEST_PERMISSIONS

    # no file
    assert generate_config_from_file("no-file.toml") is None
    assert generate_config_from_file("no-file.json") is None

    # not support file
    assert (
        generate_config_from_file(EXAMPLE_CONFIG_ROOT_PATH.joinpath("no-support.ext"))
        is None
    )

    # decode failed
    assert (
        generate_config_from_file(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("decode-failed.json")
        )
        is None
    )


def test_generate_config_from_file_with_multi_suffix():
    assert (
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-enable.toml")
        ).anonymous.enable
        is True
    )

    assert (
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-enable.toml").as_posix()
        ).anonymous.enable
        is True
    )

    assert (
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-enable.json")
        ).anonymous.enable
        is True
    )

    assert (
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("no-support.ext")
        )
        is None
    )


def test_global_config():
    # reset
    reinit_global_config()

    config = get_config()
    assert config.anonymous.enable is False

    # set
    reinit_global_config(
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-enable.toml")
        )
    )

    # check
    config = get_config()
    assert config.anonymous.enable is True
