# ASGI WebDAV Server

![GitHub](https://img.shields.io/github/license/rexzhang/asgi-webdav)
[![PyPI](https://img.shields.io/pypi/v/ASGIWebDAV)](https://pypi.org/project/ASGIWebDAV)
![Pytest Workflow Status](https://github.com/rexzhang/asgi-webdav/actions/workflows/check-pytest.yml/badge.svg)
[![codecov](https://codecov.io/gh/rexzhang/asgi-webdav/branch/main/graph/badge.svg?token=6D961MCCWN)](https://codecov.io/gh/rexzhang/asgi-webdav)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![LGTM Grade](https://img.shields.io/lgtm/grade/python/github/rexzhang/asgi-webdav)](https://lgtm.com/projects/g/rexzhang/asgi-webdav)
[![Docker Pulls](https://img.shields.io/docker/pulls/ray1ex/asgi-webdav)](https://hub.docker.com/r/ray1ex/asgi-webdav)
[![downloads](https://img.shields.io/github/downloads/rexzhang/asgi-webdav/total)](https://github.com/rexzhang/asgi-webdav/releases)

An asynchronous WebDAV server implementation, Support multi-provider, multi-account and permission control.

## Features

- [ASGI](https://asgi.readthedocs.io) standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- Support multi-provider: FileSystemProvider, MemoryProvider
- Support multi-account and permission control
- Support optional home directory
- Support store password in raw/hashlib/LDAP(experimental) mode
- Full asyncio file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 2 warning
- Browse the file directory in the browser
- Support HTTP Basic/Digest authentication
- Support response in Gzip/Brotli
- Compatible with macOS finder and Window10 Explorer

## Python Version

v3.10+

## Quickstart

[中文手册](https://rexzhang.github.io/asgi-webdav/zh/)

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
|------------|------------|---------------------------------|
| username   | `username` | -                               |
| password   | `password` | -                               |
| permission | `["+"]`    | Allow access to all directories |

## View in Browser

![](docs/web-dir-browser-screenshot.png)

## Documentation

[Github Page](https://rexzhang.github.io/asgi-webdav/)

## TODO

- Digest auth support
- SQL database provider
- Test big(1GB+) file in MemoryProvider
- display server info in page `/_/admin` or `/_/`
- OpenLDAP
- Fail2ban(docker)
- NFSProvider
- logout at the web page
- Fix MemoryProvider with macOS finder(create new file)
- rewrite MemoryProvider with mmap
- generate template URL for share(read only)

## Related Projects

- https://github.com/bootrino/reactoxide
