# Installation

## Docker

### Install

```shell
docker pull ray1ex/asgi-webdav:latest
```

### Startup server

```text
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data \
  -e UID=1000 -e GID=1000 \
  --name asgi-webdav ray1ex/asgi-webdav
```

```text
WARNING: load config value from file[/data/webdav.json] failed, [Errno 2] No such file or directory: '/data/webdav.json'
INFO: [asgi_webdav.webdav] ASGI WebDAV(v0.3.1) starting...
INFO: [asgi_webdav.distributor] Mapping Prefix: / => file:///data
INFO: [asgi_webdav.auth] Register Account: username, allow:[''], deny:[]
INFO: [uvicorn] Started server process [7]
INFO: [uvicorn] Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Default value

username is `username`, password is `password`, map `/your/data` to `http://localhost:8000`


## Python Module

### Install
```shell
git pull https://github.com/rexzhang/asgi-webdav.git
pip install -U -r requirements/base.txt
```

### Startup server

=== "Quick start"

    ```shell
    python -m asgi_webdav --root-path .
    ```

=== "Run it with config file"

    ```shell
    python -m asgi_webdav --config /your/webdav.json
    ```

### Output example
```text
2022-03-22 16:06:49,363 INFO: [asgi_webdav.server] ASGI WebDAV Server(v1.0.0) starting...
2022-03-22 16:06:49,364 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
2022-03-22 16:06:49,364 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
2022-03-22 16:06:49,844 INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Default value(quick start)

username is `username`, password is `password`, mapping current path `.` to `http://localhost:8000`


## Standalone Application

### Install 

=== "macOS"

    ```shell
    wget https://github.com/rexzhang/asgi-webdav/releases/download/v0.9.1/asgi-webdav-macos.zip
    unzip asgi-webdav-macos.zip
    ```     

=== "Windows"

    ```text
    dl https://github.com/rexzhang/asgi-webdav/releases/download/v0.9.1/asgi-webdav.exe
    ```

For other platforms or versions, please visit [GitHub Release](https://github.com/rexzhang/asgi-webdav/releases)

### Startup server

=== "macOS"

    ```text
    ./asgi_webdav -r .
    2022-03-22 16:19:45,259 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.9.1) starting...
    2022-03-22 16:19:45,259 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
    2022-03-22 16:19:45,260 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
    2022-03-22 16:19:45,374 INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://127.0.0.1:8000 (Press CTRL+C to quit)
    ```

=== "macOS with config file"

    ```text
    ./asgi-webdav --config /tmp/webdav.json
    INFO: [asgi_webdav.config] Load config value from config file:/tmp/webdav.json
    2022-03-22 16:16:58,853 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.9.1) starting...
    2022-03-22 16:16:58,853 INFO: [asgi_webdav.auth] Register User: rex-hashlib, allow:['^/$'], deny:[]
    2022-03-22 16:16:58,853 INFO: [asgi_webdav.auth] Register User: rex, allow:[''], deny:[]
    2022-03-22 16:16:58,853 INFO: [asgi_webdav.auth] Register User: user-ldap, allow:['^/$'], deny:[]
    2022-03-22 16:16:58,854 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file:///tmp/root
    2022-03-22 16:16:58,854 INFO: [asgi_webdav.web_dav] Mapping Prefix: /home => file:///tmp/homes/{user name}
    2022-03-22 16:16:58,925 INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://127.0.0.1:8000 (Press CTRL+C to quit)
    ```

=== "Windows"

    ```text
    asgi_webdav --config c:/your/webdav.json
    ```
