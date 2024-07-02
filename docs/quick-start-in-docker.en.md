# Quick Start in Docker

## Install

```
docker pull ray1ex/asgi-webdav:latest
```

## Take a Glance

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data \
  --name asgi-webdav ray1ex/asgi-webdav
```

Because there is no `webdav.json` file under `/your/data`, it will be started with the full default configuration. The
root directory mapping to `/your/data`; there is only one account, username `username`, password `password`, and all
permissions.

## Multi-Account

Create file `/your/data/webdav.json` as below

```json
{
    "account_mapping": [
        {
            "username": "user_all",
            "password": "pw1",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "user_litmus",
            "password": "pw2",
            "permissions": [
                "+^/$",
                "+^/litmus",
                "-^/litmus/other"
            ]
        },
        {
            "username": "guest",
            "anonymous": true,
            "permissions": []
        }
    ]
}
```

Restart the docker container and it will take effect. There are three accounts in total.

| username      | password | access permissions                |
|---------------|----------|-----------------------------------|
| `user_all`    | `pw1`    | all path                          |
| `user_litmus` | `pw2`    | `/` and `/litmus` and `/litmus/*` |
| `guest`       | not set  | can not access any path           |

## Path Mapping

### Configuration File

Change file `/your/data/webdav.json` as below.

```json
{
    "account_mapping": [
        {
            "username": "username",
            "password": "password",
            "permissions": [
                "+"
            ]
        }
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/litmus",
            "uri": "memory:///"
        },
        {
            "prefix": "/litmus/fs",
            "uri": "file:///data/other"
        },
        {
            "prefix": "/litmus/memory",
            "uri": "memory:///"
        }
    ]
}
```

### Create Docker Container

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data -v /your/data/other:/data/other \
  --name asgi-webdav ray1ex/asgi-webdav
```

### Path Mapping Table

| HTTP path        | path in Docker container | path in host machine |
|------------------|--------------------------|----------------------|
| `/`              | `/data/root`             | `/your/data/root`    |
| `/litmus`        | memory area A            |                      |
| `/litmus/fs`     | `/data/other`            | `/your/data/other`   |
| `/litmus/memory` | memory area B            |                      |

> The system works without creating the path `/your/data/root` on the host machine; however, accessing the URL `/` only
> results in a 404 error

## Home Directory

### Configuration File

```json
{
    "account_mapping": [
        {
            "username": "user_a",
            "password": "password",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "user_b",
            "password": "password",
            "permissions": []
        }
    ],
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file:///data/root"
        },
        {
            "prefix": "/~",
            "uri": "file:///data/homes",
            "home_dir": true
        }
    ]
}
```

### Create Docker Container

```
docker run --restart always -p 0.0.0.0:8000:8000 \
  -v /your/data:/data -v /your/data/homes:/data/homes \
  --name asgi-webdav ray1ex/asgi-webdav
```

### Path Mapping Table

| user     | URL      | path in Docker container | path in host machine          |
|----------|----------|--------------------------|-------------------------------|
| `user_a` | `/~`     | `/data/homes/user_a`     | `/your/data/homes/user_a`     |
| `user_a` | `/~/sub` | `/data/homes/user_a/sub` | `/your/data/homes/user_a/sub` |
| `user_b` | `/~`     | `/data/homes/user_b`     | `/your/data/homes/user_b`     |
| `user_b` | `/~/sub` | `/data/homes/user_b/sub` | `/your/data/homes/user_b/sub` |

- If the subdirectory of the same name corresponding to the user does not exist, it will cause the request to the home
  directory to fail. Please create paths such as `/your/data/homes/user_a` on the host by yourself.
- Even if a user does not have access to any shared directory, t hey has access to all they home directories.
- The system allows multiple home directories to exist at the same time, for example: `/~` `/home`
