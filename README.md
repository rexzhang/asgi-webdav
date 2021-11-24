# ASGI WebDAV Server

![GitHub](https://img.shields.io/github/license/rexzhang/asgi-webdav)
![Docker Image Version (tag latest semver)](https://img.shields.io/docker/v/ray1ex/asgi-webdav/latest)
![Pytest Workflow Status](https://github.com/rexzhang/asgi-webdav/actions/workflows/check-pytest.yml/badge.svg)
[![codecov](https://codecov.io/gh/rexzhang/asgi-webdav/branch/main/graph/badge.svg?token=6D961MCCWN)](https://codecov.io/gh/rexzhang/asgi-webdav)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![LGTM Grade](https://img.shields.io/lgtm/grade/python/github/rexzhang/asgi-webdav)](https://lgtm.com/projects/g/rexzhang/asgi-webdav)
[![Docker Pulls](https://img.shields.io/docker/pulls/ray1ex/asgi-webdav)](https://hub.docker.com/repository/docker/ray1ex/asgi-webdav)
[![downloads](https://img.shields.io/github/downloads/rexzhang/asgi-webdav/total)](https://github.com/rexzhang/asgi-webdav/releases)

An asynchronous WebDAV server implementation, Support multi-provider, multi-account and permission control.

## Features

- ASGI standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- Support multi-provider: FileProvider, MemoryProvider
- Support multi-account and permission control
- Support Optional home directory
- Full asyncio file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 2 warning.
- Browse the file directory in the browser
- Support HTTP Basic/Digest authentication
- Support response in Gzip/Brotli
- Compatible with macOS finder(test in WebDAVFS/3.0.0)
- Compatible with Window10 Explorer(Microsoft-WebDAV-MiniRedir/10.0.19043)

## Quickstart
[中文简明手册](https://github.com/rexzhang/asgi-webdav/blob/main/docs/quick-start.zh.md)

### Standalone Application

#### Install from Binary file

```shell
wget https://github.com/rexzhang/asgi-webdav/releases/latest/download/asgi-webdav-macos.zip
unzip asgi-webdav-macos.zip
```

For other platforms, please visit [GitHub Release](https://github.com/rexzhang/asgi-webdav/releases)

#### Install from Source Code

Python 3.9+
```shell
git pull https://github.com/rexzhang/asgi-webdav.git
cd asgi-webdav
./br_wheel.sh
```

#### Run It

```shell
asgi_webdav --root-path .
```

```text
2021-07-15 23:54:41,056 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.8.0) starting...
2021-07-15 23:54:41,056 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
2021-07-15 23:54:41,057 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
```

username is `username`, password is `password`, map `.` to `http://localhost:8000`

### Docker

#### installation

```shell
docker pull ray1ex/asgi-webdav:latest
```

#### Run It

```shell
docker run --restart always -p 0.0.0.0:80:80 -v /your/path:/data \
  --name asgi-webdav ray1ex/asgi-webdav
```

```text
WARNING: load config value from file[/data/webdav.json] failed, [Errno 2] No such file or directory: '/data/webdav.json'
INFO: [asgi_webdav.webdav] ASGI WebDAV(v0.3.1) starting...
INFO: [asgi_webdav.distributor] Mapping Prefix: / => file:///data
INFO: [asgi_webdav.auth] Register Account: username, allow:[''], deny:[]
INFO: [uvicorn] Started server process [7]
INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```

username is `username`, password is `password`, map `/your/path` to `http://localhost:80`

## Default account

`username`, `password`, `["+"]`

## View in browser

![](docs/web-dir-browser-screenshot.png)

## Known Issues

- Can not open .DMG file in macOS finder
- The type of the MemoryProvider's directory is displayed incorrectly
- After upgrade to 0.8.x with watchtower or portainer. Please change `Container.CMD` from `uvicorn asgi_webdav.docker:app --host 0.0.0.0 --port 80 --lifespan off` to `python -m asgi_webdav --host 0.0.0.0 --port 80 --in-docker-container` manually

## TODO

- Digest auth support
- SQL database provider
- PROPFIND support DAVDepth.infinity
- Test big(1GB+) file in MemoryProvider
- disable @eaDir at anywhere?

## More info
Please visit: https://rexzhang.github.io/asgi-webdav/

## Downstream Projects
- https://github.com/bootrino/reactoxide
