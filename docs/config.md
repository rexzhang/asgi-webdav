# Configuration

## Config Value Priority

Environment Variable > Config File > Default Value

## Environment Variables

| Name                 | Defaule Value | Config Object            |
| -------------------- | ------------- | ------------------------ |
| WEBDAV_LOGGING_LEVEL | INFO          | `Config.logging_level`   |
| WEBDAV_USERNAME      | username      | `Config.account_mapping` |
| WEBDAV_PASSWORD      | password      | `Config.account_mapping` |

## Config File

### When the file does not exist
When the file `/data/webdav.json` does not exist, `http://127.0.0.1/` will map
to the `/data` directory.

logging output:

```text
WARNING: load config value from file[/data/webdav.json] failed, [Errno 2] No such file or directory: '/data/webdav.json'
INFO: [asgi_webdav.webdav] ASGI WebDAV(v0.3.1) starting...
INFO: [asgi_webdav.distributor] Mapping Prefix: / => file:///data
INFO: [asgi_webdav.auth] Register Account: username, allow:[''], deny:[]
INFO: [uvicorn] Started server process [7]
INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```

### When the file exists
When the file exists, the mapping relationship is defined by the file content.

`webdav.json` basic example:

```json
{
    "account_mapping": [
        {
            "username": "user_all",
            "password": "password",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "username",
            "password": "password",
            "permissions": [
                "+^/$",
                "+^/litmus",
                "-^/litmus/other"
            ]
        },
        {
            "username": "guest",
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
            "prefix": "/litmus",
            "uri": "memory:///"
        },
        {
            "prefix": "/litmus/fs",
            "uri": "file:///data/litmus"
        },
        {
            "prefix": "/litmus/memory",
            "uri": "memory:///"
        },
        {
            "prefix": "/litmus/other",
            "uri": "memory:///"
        },
        {
            "prefix": "/~",
            "uri": "file:///data/home",
            "home_dir": true
        }
    ],
    "logging_level": "INFO"
}
```

logging output:

```text
INFO: [asgi_webdav.webdav] ASGI WebDAV(v0.3.1) starting...
INFO: [asgi_webdav.distributor] Mapping Prefix: / => file:///data/root
INFO: [asgi_webdav.distributor] Mapping Prefix: /litmus => memory:///
INFO: [asgi_webdav.distributor] Mapping Prefix: /litmus/fs => file:///data/litmus
INFO: [asgi_webdav.distributor] Mapping Prefix: /litmus/memory => memory:///
INFO: [asgi_webdav.distributor] Mapping Prefix: /litmus/other => memory:///
INFO: [asgi_webdav.distributor] Mapping Prefix: /~ => file:///data/home/{user name}
INFO: [asgi_webdav.auth] Register Account: user_all, allow:[''], deny:[]
INFO: [asgi_webdav.auth] Register Account: username, allow:['^/$', '^/litmus'], deny:['^/litmus/other']
INFO: [asgi_webdav.auth] Register Account: guest, allow:[], deny:[]
INFO: [uvicorn] Started server process [9]
INFO: [uvicorn] Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)
```

## `Config` Object

| Key                      | Value Type            | Default Value             |
| ------------------------ | --------------------- | ------------------------- |
| account_mapping          | list[Account]         | `[]`                      |
| provider_mapping         | list[Provider]        | `[]`                      |
| guess_type_extension     | GuessTypeExtension    | `GuessTypeExtension()`    |
| text_file_charset_detect | TextFileCharsetDetect | `TextFileCharsetDetect()` |
| dir_browser              | DirBrowser            | `DirBrowser()`            |
| logging_level            | str                   | `"INFO"`                  |

## `Account` Object

| Key         | Value Type   | Default Value |
| ----------- | ------------ | ------------- |
| username    | str          | -             |
| password    | str          | -             |
| permissions | list[str]    | `[]`          |

### `Permissions` Format/Example

| Value                         | Allow                | Deny         |
| ----------------------------- | -------------------- | ------------ |
| `["+"]`                       | Any                  | -            |
| `["-"]`                       | -                    | Any          |
| `["+^/$"]`                    | `/`                  | `/path`      |
| `["+^/path"]`                 | `/path`,`/path/sub`  | `/other`     |
| `["+^/path", "-^/path/sub2"]` | `/path`,`/path/sub1` | `/path/sub2` |

## `Provider` Object

| Key      | Value Type | Default Value |
| -------- | ---------- | ------------- |
| prefix   | str        | -             |
| uri      | str        | -             |
| home_dir | bool       | `false`       |

### Home Directory

- When `home_dir` is `true`, it is the home directory. The `prefix` recommends using `/~` or `/home`.

- When `home_dir` is `true` and `prefix` is `/~` and `uri` and `file:///tmp/test` and `username` is `user_x`, `http://webdav.host/~/path` will map to `file:///tmp/test/user_x/path`.

## `GuessTypeExtension` Object

| Key                    | Value Type     | Default Value | Example                    |
| ---------------------- | -------------- | ------------- | -------------------------- |
| enable                 | bool           | `true`        | -                          |
| enable_default_mapping | bool           | `true`        | -                          |
| filename_mapping       | dict[str, str] | `{}`          | `{"README": "text/plain"}` |
| suffix_mapping         | dict[str, str] | `{}`          | `{".md": "text/plain"}`    |

## `TextFileCharsetDetect` Object

| Key     | Value Type | Default Value |
| ------- | ---------- | ------------- |
| enable  | bool       | `true`        |
| default | str        | `"utf-8"`     |

## `DirBrowser` Object

| Key                          | Value Type | Default Value | Example               |
| ---------------------------- | ---------- | ------------- | --------------------- |
| enable                       | bool       | `true`        | -                     |
| enable_macos_ignore_rules    | bool       | `true`        | -                     |
| enable_windows_ignore_rules  | bool       | `true`        | -                     |
| enable_synology_ignore_rules | bool       | `true`        | -                     |
| user_ignore_rule             | str        | `""`          | `"^\.DS_Store$|^\._"` |
