from asgi_webdav.config import (
    Config,
    EnvConfig,
    Provider,
    generate_config_from_dict,
    generate_config_from_file,
    generate_config_from_file_with_multi_suffix,
    get_global_config,
    reinit_global_config,
)
from asgi_webdav.constants import (
    DEFAULT_PASSWORD_ANONYMOUS,
    DEFAULT_PERMISSIONS,
    DEFAULT_USERNAME_ANONYMOUS,
    AppEntryParameters,
    LoggingLevel,
)

from .kits.common import get_project_root_path

EXAMPLE_CONFIG_ROOT_PATH = get_project_root_path().joinpath("examples/config")

TEST_USERNAME = "test_user"
TEST_PASSWORD = "test_password"
TEST_PERMISSIONS = ["+^/$"]

TEST_ROOT_PATH_1 = "/root_path_1"
TEST_ROOT_PATH_2 = "/root_path_2"


def get_default_env_config() -> EnvConfig:
    env_config = EnvConfig()
    env_config.username = None
    env_config.password = None
    env_config.logging_level = None
    env_config.sentry_dsn = None

    return env_config


def test_defalut_config():
    config = Config()
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

    config = get_global_config()
    assert config.anonymous.enable is False

    # set
    reinit_global_config(
        generate_config_from_file_with_multi_suffix(
            EXAMPLE_CONFIG_ROOT_PATH.joinpath("anonymous-enable.toml")
        )
    )

    # check
    config = get_global_config()
    assert config.anonymous.enable is True


def test_update_from_env_config():
    config = Config()

    # keep empty
    env_config = get_default_env_config()
    config._update_from_env_config(env_config)
    assert len(config.account_mapping) == 0
    assert config.logging.level == LoggingLevel.INFO
    assert config.sentry_dsn is None

    # update
    env_config.username = TEST_USERNAME
    env_config.password = TEST_PASSWORD
    env_config.logging_level = "DEBUG"
    env_config.sentry_dsn = "https://example.com"

    config._update_from_env_config(env_config)

    assert len(config.account_mapping) == 1
    assert config.account_mapping[0].username == TEST_USERNAME
    assert config.account_mapping[0].password == TEST_PASSWORD
    assert config.logging.level == LoggingLevel.DEBUG
    assert config.sentry_dsn is not None

    # something wrong
    config = Config()
    env_config.logging_level = "something wrong"
    assert config.logging.level == LoggingLevel.INFO

    config._update_from_env_config(env_config)
    assert config.logging.level == LoggingLevel.INFO


def test_update_from_app_args():
    config = Config()

    # user
    assert config.account_mapping == []

    config._update_from_app_args(
        AppEntryParameters(admin_user=(TEST_USERNAME, TEST_PASSWORD))
    )
    assert len(config.account_mapping) == 1
    assert config.account_mapping[0].username == TEST_USERNAME
    assert config.account_mapping[0].password == TEST_PASSWORD

    # provider ---
    assert config.provider_mapping == []

    config._update_from_app_args(AppEntryParameters(root_path=TEST_ROOT_PATH_1))
    assert len(config.provider_mapping) == 1
    assert config.provider_mapping[0].prefix == "/"
    assert config.provider_mapping[0].uri == f"file://{TEST_ROOT_PATH_1}"

    # --- override config.provider_mapping[0]
    config._update_from_app_args(AppEntryParameters(root_path=TEST_ROOT_PATH_2))
    assert len(config.provider_mapping) == 1
    assert config.provider_mapping[0].uri == f"file://{TEST_ROOT_PATH_2}"

    # --- append provider(prefix == "/")
    config = Config()
    config.provider_mapping.append(
        Provider(prefix="/other", uri="file://other", type="memory")
    )
    assert len(config.provider_mapping) == 1

    config._update_from_app_args(AppEntryParameters(root_path=TEST_ROOT_PATH_1))
    assert len(config.provider_mapping) == 2
    assert config.provider_mapping[1].prefix == "/"
    assert config.provider_mapping[1].uri == f"file://{TEST_ROOT_PATH_1}"
