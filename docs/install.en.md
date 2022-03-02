# Installation

## Docker

### Install

```shell
docker pull ray1ex/asgi-webdav:latest
```

### Quick start

```shell
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


## Standalone Application

### Install 
=== "from Binary file"

    ```shell
    wget https://github.com/rexzhang/asgi-webdav/releases/latest/download/asgi-webdav-macos.zip
    unzip asgi-webdav-macos.zip
    ```     

=== "from Source Code"

    ```shell
    git pull https://github.com/rexzhang/asgi-webdav.git
    cd asgi-webdav
    ./br_wheel.sh
    ```

For other platforms, please visit [GitHub Release](https://github.com/rexzhang/asgi-webdav/releases)

### Quick start

```shell
asgi_webdav --root-path .
```

```text
2021-07-15 23:54:41,056 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.8.0) starting...
2021-07-15 23:54:41,056 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
2021-07-15 23:54:41,057 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
```

### Default value

username is `username`, password is `password`, map `.` to `http://localhost:8000`
