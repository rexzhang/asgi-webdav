# ASGI WebDAV Server

[![](https://travis-ci.org/rexzhang/asgi-webdav.svg?branch=main)](https://travis-ci.org/rexzhang/asgi-webdav)
[![Coverage Status](https://coveralls.io/repos/github/rexzhang/asgi-webdav/badge.svg?branch=main)](https://coveralls.io/github/rexzhang/asgi-webdav?branch=main)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

An asynchronous WebDAV server implementation, support multi-provider.

# Requirement

- Python3.9+

# Features

- ASGI standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- Support multi-provider: FileProvider, MemoryProvider
- Full asyncio file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 2
  warning.
- Compatible macOS finder

# DAVProvider
| DAVProvider    | URI                                                         |                                   |
| -------------- | ----------------------------------------------------------- | --------------------------------- |
| FileProvider   | [file://...](https://en.wikipedia.org/wiki/File_URI_scheme) | data is stored in the file system |
| MemoryProvider | memory:///                                                  | data is stored in the memory      |

# Docker

## Install

```shell
docker pull ray1ex/asgi-webdav:latest
```

## Start server

```shell
docker run --restart always -p 0.0.0.0:80:80 -v /your/path:/data --name asgi-webdav ray1ex/asgi-webdav
```

## Environment variables

| Name          | Defaule Value |                         |
| ------------- | ------------- | ----------------------- |
| LOGGING_LEVEL | INFO          | support: DEBUG, INFO... |
| USERNAME      | username      |                         |
| PASSWORD      | password      |                         |

## Configuration

### Config Value Priority

Environment Variable > Config File > Default Value

### Config File

When the file `/data/webdav.json` does not exist, `http://127.0.0.1/` will map
to the `/data` directory.

logging output:

```text
WARNING: load config[/data] value from file failed, [Errno 2] No such file or directory: '/data/webdav.json'
2021-03-10 08:53:08,763 INFO: [asgi_webdav.distributor] Mapping: / => file:///data
2021-03-10 08:53:08,765 INFO: [uvicorn] Started server process [7]
2021-03-10 08:53:08,765 INFO: [uvicorn] Waiting for application startup.
2021-03-10 08:53:08,766 INFO: [uvicorn] ASGI 'lifespan' protocol appears unsupported.
2021-03-10 08:53:08,766 INFO: [uvicorn] Application startup complete.
2021-03-10 08:53:08,767 INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```

When the file exists, the mapping relationship is defined by the file content.

`webdav.json` example:

```json
{
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/joplin/",
            "uri": "file:///mnt/joplin"
        },
        {
            "prefix": "/joplin/locks",
            "uri": "memory:///"
        }
    ]
}
```

logging output:

```text
2021-03-14 12:35:39,609 INFO: [asgi_webdav.distributor] Mapping: / => file:///data/root
2021-03-14 12:35:39,610 INFO: [asgi_webdav.distributor] Mapping: /joplin => file:///mnt/joplin
2021-03-14 12:35:39,610 INFO: [asgi_webdav.distributor] Mapping: /joplin/locks => memory:///
2021-03-14 12:35:39,764 INFO: [uvicorn] Started server process [7]
2021-03-14 12:35:39,765 INFO: [uvicorn] Waiting for application startup.
2021-03-14 12:35:39,967 INFO: [uvicorn] ASGI 'lifespan' protocol appears unsupported.
2021-03-14 12:35:39,969 INFO: [uvicorn] Application startup complete.
2021-03-14 12:35:39,973 INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```

# TODO

- digest auth support
- sql provider
- PROPFIND support DAVDepth.infinity
- can not open DMG file int macOS finder
- web file browser
