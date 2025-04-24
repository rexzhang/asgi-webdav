# Overview

![GitHub](https://img.shields.io/github/license/rexzhang/asgi-webdav)
[![PyPI](https://img.shields.io/pypi/v/ASGIWebDAV)](https://pypi.org/project/ASGIWebDAV)
[![PyPI - Version](https://img.shields.io/pypi/pyversions/ASGIWebDAV.svg)](https://pypi.org/project/ASGIWebDAV/)
![Pytest Workflow Status](https://github.com/rexzhang/asgi-webdav/actions/workflows/check-pytest.yml/badge.svg)
[![codecov](https://codecov.io/gh/rexzhang/asgi-webdav/branch/main/graph/badge.svg?token=6D961MCCWN)](https://codecov.io/gh/rexzhang/asgi-webdav)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Docker Pulls](https://img.shields.io/docker/pulls/ray1ex/asgi-webdav)](https://hub.docker.com/r/ray1ex/asgi-webdav)
![[PyPI - Downloads](https://pypi.org/project/ASGIWebDAV/)](https://img.shields.io/pypi/dm/ASGIWebDAV)
[![GitHub Downloads](https://img.shields.io/github/downloads/rexzhang/asgi-webdav/total)](https://github.com/rexzhang/asgi-webdav/releases)

An asynchronous WebDAV server implementation, Support multi-provider, multi-account and permission control.

## Features

- [ASGI](https://asgi.readthedocs.io) standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- Support multi-provider: FileSystemProvider, MemoryProvider
- Support multi-account and permission control
- Support optional home directory
- Support store password in raw/hashlib/LDAP(experimental) mode
- Full asyncio file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 3 warning
- Browse the file directory in the browser
- Support HTTP Basic/Digest authentication
- Support response in Gzip/Brotli
- Compatible with macOS finder and Window10 Explorer

## Quick Start

```shell
docker pull ray1ex/asgi-webdav
docker run -dit --restart unless-stopped \
  -p 8000:8000 \
  -e UID=1000 -e GID=1000 \
  -v /your/data:/data \
  --name asgi-webdav ray1ex/asgi-webdav
```

## Default Account

|            | value      | description                     |
| ---------- | ---------- | ------------------------------- |
| username   | `username` | -                               |
| password   | `password` | -                               |
| permission | `["+"]`    | Allow access to all directories |

## View in Browser

![](web-dir-browser-screenshot.png)
