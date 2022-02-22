# Usage

## Config Value Priority

Command Line Interface Args > Environment Variable > Configuration File > Default Value

## Command Line Interface Args

- Introduced in 0.8
- Last updated in 0.8

```
asgi_webdav --help
Usage: asgi_webdav [OPTIONS]

  Run ASGI WebDAV server

Options:
  -V, --version              Print version info and exit.
  -H, --host TEXT            Bind socket to this host.  [default: 127.0.0.1]
  -P, --port INTEGER         Bind socket to this port.  [default: 8000]
  -u, --user <TEXT TEXT>...  Administrator username/password. [default:
                             username password]
  -r, --root-path TEXT       Mapping provider URI to path '/'. [default: None]
  -c, --config TEXT          Load configuration from file.  [default: None]
  --dev                      Enter Development mode, DON'T use it in
                             production!
  --in-docker-container      When work in docker container, enable it.
  --help                     Show this message and exit.
```

### Example

```shell
python -m asgi_webdav --root-path .
2021-07-30 15:08:44,084 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.8.0) starting...
2021-07-30 15:08:44,085 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
2021-07-30 15:08:44,085 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
2021-07-30 15:08:44,085 INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

username is username, password is password, map . to http://localhost:8000

## Environment Variables

| Name                 | Defaule Value | Config Object            |
|----------------------|---------------|--------------------------|
| WEBDAV_LOGGING_LEVEL | INFO          | `Config.logging_level`   |
| WEBDAV_USERNAME      | username      | `Config.account_mapping` |
| WEBDAV_PASSWORD      | password      | `Config.account_mapping` |

## Configuration file

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
            "username": "username",
            "password": "password",
            "permissions": [
                "+"
            ]
        },
        {
            "username": "litmus",
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

- Introduced in 0.1
- Last updated in 0.5

| Key                      | Value Type            | Default Value             |
|--------------------------|-----------------------|---------------------------|
| account_mapping          | list[User]            | `[]`                      |
| http_digest_auth         | HTTPDigestAuth        | `HTTPDigestAuth()`        |
| provider_mapping         | list[Provider]        | `[]`                      |
| guess_type_extension     | GuessTypeExtension    | `GuessTypeExtension()`    |
| text_file_charset_detect | TextFileCharsetDetect | `TextFileCharsetDetect()` |
| compression              | Compression           | `Compression()`           |
| dir_browser              | DirBrowser            | `DirBrowser()`            |
| logging_level            | str                   | `"INFO"`                  |

## `User` Object

- Introduced in 0.3.1
- Last updated in 0.7.0

| Key         | Value Type  | Default Value |
|-------------|-------------|---------------|
| username    | str         | -             |
| password    | str         | -             |
| permissions | list[str]   | `[]`          |
| admin       | bool        | `false`       |

- When the value of `admin` is `true`, the user can access the web page `/_/admin/xxx`

### `Permissions` Format/Example

- Introduced in 0.3.1
- Last updated in 0.3.1

| Value                         | Allow                 | Deny          |
|-------------------------------|-----------------------|---------------|
| `["+"]`                       | Any                   | -             |
| `["-"]`                       | -                     | Any           |
| `["+^/$"]`                    | `/`                   | `/path`       |
| `["+^/path"]`                 | `/path`,`/path/sub`   | `/other`      |
| `["+^/path", "-^/path/sub2"]` | `/path`,`/path/sub1`  | `/path/sub2`  |

## `HTTPDigestAuth` Object

- Introduced in 0.7.0
- Last updated in 0.9.0

| Key           | Value Type | Default Value |
|---------------|------------|---------------|
| enable        | bool       | `false`       |
| enable_rule   | str        | ``            |
| disable_rule  | str        | `neon/`       |

- When `enable` is `true`, the `disable_rule` is valid
- When `enable` is `false`, the `enable_rule` is valid

## `Provider` Object

- Introduced in 0.1
- Last updated in 0.3.1

| Key       | Value Type | Default Value |
|-----------|------------|---------------|
| prefix    | str        | -             |
| uri       | str        | -             |
| home_dir  | bool       | `false`       |

### Home Directory

- When `home_dir` is `true`, it is the home directory. The `prefix` recommends using `/~` or `/home`.

- When `home_dir` is `true` and `prefix` is `/~` and `uri` and `file:///tmp/test` and `username` is `user_x`, `http://webdav.host/~/path` will map to `file:///tmp/test/user_x/path`.

## `GuessTypeExtension` Object

- Introduced in 0.4
- Last updated in 0.4

| Key                    | Value Type     | Default Value | Example                    |
|------------------------|----------------|---------------|----------------------------|
| enable                 | bool           | `true`        | -                          |
| enable_default_mapping | bool           | `true`        | -                          |
| filename_mapping       | dict[str, str] | `{}`          | `{"README": "text/plain"}` |
| suffix_mapping         | dict[str, str] | `{}`          | `{".md": "text/plain"}`    |

## `TextFileCharsetDetect` Object 

- Introduced in 0.5 
- Last updated in 0.5

| Key      | Value Type | Default Value |
|----------|------------|---------------|
| enable   | bool       | `false`       |
| default  | str        | `"utf-8"`     |

## `DirFileIgnore` Object

- Introduced in 1.0
- Last updated in 1.0

| Key                  | Value Type | Default Value | Example                                                                                                                               |
|----------------------|------------|---------------|---------------------------------------------------------------------------------------------------------------------------------------|
| enable               | bool       | `true`        | -                                                                                                                                     |
| enable_default_rules | bool       | `true`        | -                                                                                                                                     |
| user_rules           | dict       | `{}`          | [`like default`](https://github.com/rexzhang/asgi-webdav/blob/231c233df58456e81b7264a65c1bce7d37047d19/asgi_webdav/constants.py#L326) |

## `Compression` Object

- Introduced in 0.5
- Last updated in 0.5

| Key                    | Value Type       | Default Value | Example                      |
|------------------------|------------------|---------------|------------------------------|
| enable_gzip            | bool             | `true`        | -                            |
| enable_brotli          | bool             | `true`        | -                            |
| level                  | DAVCompressLevel | `"recommend"` | `"best"`                     |
| user_content_type_rule | str              | `""`          | `"^application/xml$|^text/"` |

| DAVCompressLevel | Gzip Level | Brotli Level |
|------------------|------------|--------------|
| fast             | 1          | 1            |
| recommend        | 4          | 4            |
| best             | 9          | 11           |
