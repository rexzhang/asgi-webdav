from dataclasses import dataclass

from fabric import task
from invoke.context import Context

_DOCKER_PULL = "docker pull --platform=linux/amd64"
_DOCKER_BUILD = "docker buildx build --platform=linux/amd64 --build-arg BUILD_DEV=rex"
_c = Context()


def say_it(message: str):
    print(message)
    _c.run(f"say {message}")


@task
def docker_pull_base_image(c):
    c.run(f"{_DOCKER_PULL} {ev.DOCKER_BASE_IMAGE}")
    print("pull docker base image finished.")


@task
def build(c):
    docker_pull_base_image(c)
    docker_build(c)


@task
def docker_push_image(c):
    print("push docker image to register...")

    c.run(f"docker push {ev.DOCKER_IMAGE_FULL_NAME}")
    say_it("push finished.")


@task
def docker_pull_image(c):
    c.run(f"{_DOCKER_PULL} {ev.DOCKER_IMAGE_FULL_NAME}")
    say_it("pull image finished.")


@task
def docker_send_image(c):
    print("send docker image to deploy server...")
    c.run(
        f'docker save {ev.DOCKER_IMAGE_FULL_NAME} | gzip | ssh {ev.DEPLOY_SSH_USER}@{ev.DEPLOY_SSH_HOST} -p {ev.DEPLOY_SSH_PORT} "gunzip | docker load"'
    )
    say_it("send image finished")


def _recreate_container(c, container_name: str, docker_run_cmd: str):
    if ev.DEPLOY_STAGE == "local":
        c.run(f"mkdir {ev.DEPLOY_WORK_PATH}", warn=True)

    c.run(f"docker container stop {container_name}", warn=True)
    c.run(f"docker container rm {container_name}", warn=True)
    c.run(f"cd {ev.DEPLOY_WORK_PATH} && {docker_run_cmd}")

    say_it(f"deploy {container_name} finished")


@dataclass
class EnvValue:
    APP_NAME = "asgi-webdav"

    # Target Host
    DEPLOY_STAGE = "dev"
    DEPLOY_SSH_HOST = "dev.h.rexzhang.com"
    DEPLOY_SSH_PORT = 22
    DEPLOY_SSH_USER = "root"
    DEPLOY_WORK_PATH = "/root/asgi-webdav"

    # Docker Register
    CR_HOST_NAME = "cr.h.rexzhang.com"
    CR_NAME_SPACE = "rex"

    # Docker Image
    DOCKER_BASE_IMAGE = "python:3.13-alpine"

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
        self.DEPLOY_WORK_PATH = "/tmp/webdav"
        self.CONTAINER_GID = 20
        self.CONTAINER_UID = 501


ev = EnvValue()


@task
def env_localhost(c):
    ev.switch_env_local()


def docker_build(c):
    print("build docker image...")
    c.run(f"{_DOCKER_BUILD} -t {ev.DOCKER_IMAGE_FULL_NAME} .")

    say_it("docker image build finished")


@task
def deploy(c):
    print("deploy container...")

    _recreate_container(
        c=c,
        container_name=ev.get_container_name(),
        docker_run_cmd=f"""docker run -dit --restart unless-stopped \
 -p 0.0.0.0:8000:8000 \
 -v {ev.DEPLOY_WORK_PATH}:/data \
 -e GID={ev.CONTAINER_GID} -e UID={ev.CONTAINER_UID} \
 -e WEBDAV_LOGGING_LEVEL=DEBUG \
 --name {ev.get_container_name()} \
 {ev.DOCKER_IMAGE_FULL_NAME}""",
    )


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
    c.run("mkdocs serve")
