from dataclasses import asdict, dataclass

from fabric import task

_DOCKER_PULL = "docker pull --platform=linux/amd64"
_DOCKER_BUILD = "docker buildx build --platform=linux/amd64 --build-arg BUILD_DEV=rex"


@dataclass
class EnvValue:
    # Docker Container Register
    CR_HOST_NAME = "cr.h.rexzhang.com"
    CR_NAME_SPACE = "ray1ex"

    # Docker Image
    DOCKER_BASE_IMAGE_TAG = "cr.rexzhang.com/library/python:3.13-alpine"
    DOCKER_IMAGE_NAME = "asgi-webdav"

    @property
    def DOCKER_IMAGE_FULL_NAME(self) -> str:
        return f"{self.CR_HOST_NAME}/{self.CR_NAME_SPACE}/{self.DOCKER_IMAGE_NAME}"

    # Docker Container
    CONTAINER_NAME = "asgi-webdav"
    CONTAINER_GID = 20
    CONTAINER_UID = 501

    def asdict(self) -> dict:
        return asdict(self)


ev = EnvValue()


@task
def docker_pull_base_image(c):
    c.run(f"{_DOCKER_PULL} {ev.DOCKER_BASE_IMAGE_TAG}")
    print("pull docker base image finished.")


@task()
def docker_build(c):
    print("build docker image...")
    c.run(f"{_DOCKER_BUILD} -t {ev.DOCKER_IMAGE_FULL_NAME} .")
    c.run("docker image prune -f")

    print("build finished.")

    c.run("say docker image build finished")


@task
def docker_push_image(c):
    print("push docker image to register...")

    c.run(f"docker push {ev.DOCKER_IMAGE_FULL_NAME}")
    print("push finished.")


@task
def docker_pull_image(c):
    c.run(f"{_DOCKER_PULL} {ev.DOCKER_IMAGE_FULL_NAME}")
    print("pull image finished.")


@task
def docker_test(c):
    print("startup container...")

    c.run(f"docker container stop {ev.CONTAINER_NAME}", warn=True)
    c.run(f"docker container rm {ev.CONTAINER_NAME}", warn=True)
    c.run("mkdir /tmp/webdav", warn=True)
    c.run(
        f"""docker run -dit --restart unless-stopped \
 -p 0.0.0.0:8000:8000 \
 -v /tmp/webdav:/data \
 -e GID={ev.CONTAINER_GID} -e UID={ev.CONTAINER_UID} \
 -e WEBDAV_LOGGING_LEVEL=DEBUG \
 --name {ev.CONTAINER_NAME} {ev.DOCKER_IMAGE_FULL_NAME}"""
    )
    c.run(f"docker container logs -f {ev.CONTAINER_NAME}")


@task
def pypi_build(c):
    c.run("python -m pip install -U -r requirements.d/pypi.txt")
    c.run("rm -rf build/*")
    c.run("rm -rf dist/*")
    c.run("python -m build")


@task
def pypi_public(c):
    c.run(
        "python -m twine upload --repository-url https://upload.pypi.org/legacy/ dist/*"
    )


@task
def mkdoc(c):
    c.run("mkdocs serve")
