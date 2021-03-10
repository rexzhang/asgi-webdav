# ASGI WebDAV Server

# Requirement

- Python3.9+

# Features

- ASGI standard
- WebDAV standard: [RFC4918](https://www.ietf.org/rfc/rfc4918.txt)
- multi-provider support
- Async file IO
- Passed all [litmus(0.13)](http://www.webdav.org/neon/litmus) test, except 2
  warning.


# Docker

## Install

```shell
docker push ray1ex/asgi-webdav:latest
```

## Start server

```shell
docker run --restart always -p 80:80 -v /your/path:/data
```

## Environment variables

- LOGGING_LEVEL
    - default: INFO
    - support: DEBUG, INFO...
- USERNAME
    - default: username
- PASSWORD
    - default: password

## Configuration

### Priority

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
        }
    ]
}
```

logging output:

```text
2021-03-10 08:50:20,631 INFO: [asgi_webdav.distributor] Mapping: / => file:///data/root
2021-03-10 08:50:20,632 INFO: [asgi_webdav.distributor] Mapping: /joplin/ => file:///mnt/joplin
2021-03-10 08:50:20,849 INFO: [uvicorn] Started server process [6]
2021-03-10 08:50:20,850 INFO: [uvicorn] Waiting for application startup.
2021-03-10 08:50:21,351 INFO: [uvicorn] ASGI 'lifespan' protocol appears unsupported.
2021-03-10 08:50:21,354 INFO: [uvicorn] Application startup complete.
2021-03-10 08:50:21,356 INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```
