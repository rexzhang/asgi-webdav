# Introduction

![Docker Image Version (tag latest semver)](https://img.shields.io/docker/v/ray1ex/asgi-webdav/latest)
![Pytest Workflow Status](https://github.com/rexzhang/asgi-webdav/actions/workflows/test.yml/badge.svg)
[![codecov](https://codecov.io/gh/rexzhang/asgi-webdav/branch/main/graph/badge.svg?token=6D961MCCWN)](https://codecov.io/gh/rexzhang/asgi-webdav)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
![Docker Pulls](https://img.shields.io/docker/pulls/ray1ex/asgi-webdav)

An asynchronous WebDAV server implementation, Support multi-provider, multi-account and permission control.

## Features

- ASGI standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- Support multi-provider: FileProvider, MemoryProvider
- Support multi-account and permission control
- Support Optional home directory
- Full asyncio file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 2
  warning.
- Browse the file directory in the browser
- Support HTTP Basic/Digest authentication
- Support response in Gzip/Brotli
- Compatible with macOS finder(test in WebDAVFS/3.0.0)
- Compatible with Window10 Explorer(Microsoft-WebDAV-MiniRedir/10.0.19043)

## Quickstart

### Install to docker

```shell
docker pull ray1ex/asgi-webdav:latest
```

### Run it

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

### Default account

`username`, `password`, `["+"]`

### View in browser

![](web-dir-browser-screenshot.png)
