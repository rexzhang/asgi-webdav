from fabric import task

from os import getenv


class DevEnv:
    docker_image_name_prefix: str = ""
    gid: int = 20
    uid: int = 501

    def __init__(self) -> None:
        self.dev_env = getenv("DEV_ENV", "")
        if self.dev_env != "rex":
            return

        self.docker_image_name_prefix = "cr.h.rexzhang.com/"


dev_env = DevEnv()


@task()
def docker_build(c):
    print("build docker image...")

    c.run("docker pull python:3.12-alpine")
    c.run(
        f"docker build -t {dev_env.docker_image_name_prefix}ray1ex/asgi-webdav . --build-arg DEV_ENV={dev_env.dev_env}"
    )

    c.run("say docker image build finished")


@task
def docker_test(c):
    print("startup container...")

    c.run("docker container stop asgi-webdav", warn=True)
    c.run("docker container rm asgi-webdav", warn=True)
    c.run("mkdir /tmp/webdav", warn=True)
    c.run(
        f"""docker run -dit --restart unless-stopped \
 -p 0.0.0.0:8000:8000 \
 -v /tmp/webdav:/data \
 -e UID={dev_env.uid} -e GID={dev_env.gid} \
 -e WEBDAV_LOGGING_LEVEL=DEBUG \
 --name asgi-webdav {dev_env.docker_image_name_prefix}ray1ex/asgi-webdav"""
    )
    c.run("docker container logs -f asgi-webdav")


@task
def docker_push(c):
    c.run(f"docker push {dev_env.docker_image_name_prefix}ray1ex/asgi-webdav")


@task
def pypi_build(c):
    c.run("python -m pip install -U -r requirements/pypi.txt")
    c.run("rm -rf build/*")
    c.run("rm -rf dist/*")
    c.run("python -m build")


@task
def pypi_public(c):
    c.run(
        "python -m twine upload --repository-url https://upload.pypi.org/legacy/ dist/*"
    )
