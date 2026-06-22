import os
from dataclasses import dataclass
from typing import Any, overload

from dotenv import dotenv_values
from fabric import Connection, task
from invoke.context import Context

_DOCKER_PULL = "docker pull --platform=linux/amd64"
_DOCKER_BUILD = "docker buildx build --platform=linux/amd64 --build-arg BUILD_ENV=rex"  # TODO: t-string
_DOCKER_RUN = "docker run --platform=linux/amd64"
_c = Context()


_MISSING = object()


class EnvValue:
    data: dict[str, str]

    def __init__(self, env_path: str = ".env") -> None:
        base_env = os.environ.copy()
        file_env = dotenv_values(env_path)
        self.data = {k: v for k, v in {**base_env, **file_env}.items() if v is not None}

    @overload
    def get(self, k: str) -> str | None: ...

    @overload
    def get(self, k: str, default: str) -> str: ...

    def get(self, k: str, default: Any = _MISSING) -> str | None:
        value = self.data.get(k)
        if value is not None:
            return value

        if default is _MISSING:
            return None

        if default is None:
            raise ValueError(f"The default value for key '{k}' cannot be None.")

        return default

    def __repr__(self) -> str:
        import json

        return json.dumps(self.data, indent=2)


def say_it(message: str):
    print(message)
    _c.run(f"say {message}")


@task
def docker_pull_base_image(c):
    c.run(f"{_DOCKER_PULL} {DV.DOCKER_BASE_IMAGE_TAG}")
    print("pull docker base image finished.")


@task
def docker_push_image(c):
    print("push docker image to register...")

    c.run(f"docker push {DV.DOCKER_IMAGE_FULL_NAME}")
    say_it("push finished.")


@task
def docker_pull_image(c):
    c.run(f"{_DOCKER_PULL} {DV.DOCKER_IMAGE_FULL_NAME}")
    say_it("pull image finished.")


@task
def docker_send_image(c):
    print("send docker image to deploy server...")
    c.run(
        f'docker save {DV.DOCKER_IMAGE_FULL_NAME} | gzip | ssh {DV.DEPLOY_SSH_USER}@{DV.DEPLOY_SSH_HOST} -p {DV.DEPLOY_SSH_PORT} "gunzip | docker load"'
    )
    say_it("send image finished")


def _recreate_container(c, container_name: str, docker_run_cmd: str):
    c.run(f"docker container stop {container_name}", warn=True)
    c.run(f"docker container rm {container_name}", warn=True)
    c.run(f"cd {DV.DEPLOY_WORK_PATH} && {docker_run_cmd}")

    say_it(f"deploy {container_name} finished")


@dataclass
class DeployValue:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._env_value = EnvValue()

    def _get_value_from_env(self, name: str, default: str | None = None) -> str:
        if default is None:
            value = self._env_value.get(
                f"{self.APP_NAME.replace("-", "_").upper()}_{self.DEPLOY_STAGE.upper()}_{name.upper()}"
            )
        else:
            value = self._env_value.get(
                f"{self.APP_NAME.replace("-", "_").upper()}_{self.DEPLOY_STAGE.upper()}_{name.upper()}",
                default,
            )

        if value is None:
            raise Exception(f"{name}, {default}")

        return value

    APP_NAME = "asgi-webdav"

    # Target Host
    DEPLOY_STAGE = "dev"

    @property
    def DEPLOY_SSH_HOST(self) -> str:
        return self._get_value_from_env("DEPLOY_SSH_HOST")

    @property
    def DEPLOY_SSH_PORT(self) -> int:
        return int(self._get_value_from_env("DEPLOY_SSH_PORT"))

    @property
    def DEPLOY_SSH_USER(self) -> str:
        return self._get_value_from_env("DEPLOY_SSH_USER", "root")

    DEPLOY_WORK_PATH = "~/apps/asgi-webdav"

    # Docker Register
    CR_HOST_NAME = "cr.h.rexzhang.com"
    CR_NAME_SPACE = "rex"

    # Docker Image
    DOCKER_BASE_IMAGE_TAG = "python:3.14-alpine"

    @property
    def DOCKER_IMAGE_FULL_NAME(self) -> str:
        name = f"{self.CR_HOST_NAME}/{self.CR_NAME_SPACE}/{self.APP_NAME}"
        if self.DEPLOY_STAGE != "prd":
            name += f":{self.DEPLOY_STAGE}"

        return name

    # Docker Container
    def get_container_name(self, module: str | None = None) -> str:
        if module is None:
            return f"{self.APP_NAME}-{self.DEPLOY_STAGE}"

        return f"{self.APP_NAME}-{self.DEPLOY_STAGE}-{module}"

    CONTAINER_GID = 1000
    CONTAINER_UID = 1000

    def switch_env_local(self):
        self.DEPLOY_STAGE = "local"
        self.DEPLOY_WORK_PATH = "/tmp"
        self.CONTAINER_GID = 20
        self.CONTAINER_UID = 501

    def switch_env_prd(self):
        self.DEPLOY_STAGE = "prd"


DV = DeployValue()


@task
def env_local(c):
    DV.switch_env_local()


@task
def env_prd(c):
    DV.switch_env_prd()


def docker_build(c):
    print("build docker image...")
    from asgi_webdav import __version__

    c.run(
        f"{_DOCKER_BUILD} --build-arg IMAGE_VERSION={__version__} -t {DV.DOCKER_IMAGE_FULL_NAME} ."
    )

    say_it("docker image build finished")


@task
def build(c):
    docker_pull_base_image(c)
    docker_build(c)


def docker_deploy(c):
    docker_run_cmd = f"""{_DOCKER_RUN} -dit --restart unless-stopped \
 -p 0.0.0.0:8000:8000 \
 -v {DV.DEPLOY_WORK_PATH}:/data \
 -e GID={DV.CONTAINER_GID} -e UID={DV.CONTAINER_UID} \
 --name {DV.get_container_name()} \
 {DV.DOCKER_IMAGE_FULL_NAME}"""

    _recreate_container(
        c=c, container_name=DV.get_container_name(), docker_run_cmd=docker_run_cmd
    )


def run_restart_script(c):
    c.run(f"cd {DV.DEPLOY_WORK_PATH} && ./UpdateContainer.sh")


@task
def deploy(c):
    print("deploy container...")

    match DV.DEPLOY_STAGE:
        case "local":
            docker_deploy(c)

        case "dev":
            docker_push_image(c)
            c = Connection(
                host=DV.DEPLOY_SSH_HOST,
                port=DV.DEPLOY_SSH_PORT,
                user=DV.DEPLOY_SSH_USER,
            )
            docker_pull_image(c)
            docker_deploy(c)

        case "prd":
            docker_push_image(c)
            c = Connection(
                host=DV.DEPLOY_SSH_HOST,
                port=DV.DEPLOY_SSH_PORT,
                user=DV.DEPLOY_SSH_USER,
            )
            docker_pull_image(c)
            run_restart_script(c)


@task
def pypi_build(c):
    c.run("python -m pip install -U -r requirements.d/pypi.txt")
    c.run("rm -rf build/*")
    c.run("rm -rf dist/*")
    c.run("python -m build")


@task
def pypi_public(c):
    c.run("python -m twine upload dist/*")


@task
def mkdocs(c):
    c.run("mkdocs serve --livereload")
