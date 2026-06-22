# Config File

## `webdav.toml` file

### Convert `.json` to `.toml`

please search `convert json toml` in your browser.

### When the file does not exist

When the file `/data/webdav.toml(.json)` does not exist, `http://127.0.0.1/` will map to the `/data` directory.

#### logging output

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

#### Example

```toml
[[account_mapping]]
username = "username"
password = "password"
permissions = [ "+" ]

[[account_mapping]]
username = "litmus"
password = "password"
permissions = [ "+^/$", "+^/litmus", "-^/litmus/other" ]

[[account_mapping]]
username = "guest"
password = "password"
permissions = [ ]

[anonymous]
enable = true

[[provider_mapping]]
prefix = "/"
uri = "file:///data/root"
read_only = true

[[provider_mapping]]
prefix = "/provider"
uri = "memory:///"
read_only = true

[[provider_mapping]]
prefix = "/provider/fs"
uri = "file:///data/litmus"

[[provider_mapping]]
prefix = "/provider/memory"
uri = "memory:///"
ignore_property_extra = false

[[provider_mapping]]
prefix = "/~"
uri = "file:///data/home"
home_dir = true
```

More example please check `examples/config/*.toml` in codebase.

#### logging output

```text
INFO: [asgi_webdav.server] ASGI WebDAV Server(v1.3.2) starting...
INFO: [asgi_webdav.auth] Register Account: username, allow:[''], deny:[]
INFO: [asgi_webdav.auth] Register Account: litmus, allow:['^/$', '^/litmus'], deny:['^/litmus/other']
INFO: [asgi_webdav.auth] Register Account: guest, allow:[], deny:[]
INFO: [asgi_webdav.auth] Register Account: anonymous, allow:['^/public'], deny:[]
INFO: [asgi_webdav.web_dav] Mapping Prefix: / --[ReadOnly]--> file:///data/root
INFO: [asgi_webdav.web_dav] Mapping Prefix: /provider --[ReadOnly]--> memory:///
INFO: [asgi_webdav.web_dav] Mapping Prefix: /provider/fs --> file:///tmp
INFO: [asgi_webdav.web_dav] Mapping Prefix: /provider/memory --> memory:///
INFO: [asgi_webdav.web_dav] Mapping Prefix: /~ --[Home]--> file:///data/home/{user name}
INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://localhost:8000 (Press CTRL+C to quit)
```

## `Config` Object

root object

- Introduced in 0.1
- Last updated in 1.6.0

| Key                      | Use For  | Value Type              | Default Value             |
| ------------------------ | -------- | ----------------------- | ------------------------- |
| account_mapping          | auth     | `list[User]`            | `[]`                      |
| anonymous                | auth     | `Anonymous`             | `Anonymous()`             |
| http_basic_auth          | auth     | `HTTPBasicAuth`         | `HTTPBasicAuth()`         |
| http_digest_auth         | auth     | `HTTPDigestAuth`        | `HTTPDigestAuth()`        |
| provider_mapping         | mapping  | `list[Provider]`        | `[]`                      |
| hide_file_in_dir         | rules    | `HideFileInDir`         | `HideFileInDir()`         |
| guess_type_extension     | rules    | `GuessTypeExtension`    | `GuessTypeExtension()`    |
| text_file_charset_detect | rules    | `TextFileCharsetDetect` | `TextFileCharsetDetect()` |
| compression              | response | `Compression`           | `Compression()`           |
| cors                     | response | `CORS`                  | `CORS()`                  |
| enable_dir_browser       | response | `bool`                  | `true`                    |
| logging                  | other    | `Logging`               | `"Logging()"`             |
| sentry_dsn               | other    | `str`                   | `None`                    |

## for Authentication

### `User` Object

- Introduced in 0.3.1
- Last updated in 0.7

| Key         | Value Type | Default Value |
| ----------- | ---------- | ------------- |
| username    | str        | -             |
| password    | str        | -             |
| permissions | list[str]  | `[]`          |
| admin       | bool       | `false`       |

- When the value of `admin` is `true`, the user can access the web page `/_/admin/xxx`

#### `Permissions` Format/Example

- Introduced in 0.3.1
- Last updated in 0.3.1

| Value                         | Allow                | Deny         |
| ----------------------------- | -------------------- | ------------ |
| `["+"]`                       | Any                  | -            |
| `["-"]`                       | -                    | Any          |
| `["+^/$"]`                    | `/`                  | `/path`      |
| `["+^/path"]`                 | `/path`,`/path/sub`  | `/other`     |
| `["+^/path", "-^/path/sub2"]` | `/path`,`/path/sub1` | `/path/sub2` |

### `Anonymous` Object

- Introduced in 1.6
- Last updated in 1.6

| Key                       | Value Type | Default Value                  |
| ------------------------- | ---------- | ------------------------------ |
| enable                    | bool       | `false`                        |
| user                      | `User`     | `User("anonymous", "", ["+"])` |
| allow_missing_auth_header | bool       | `true`                         |

- Anonymous accounts can be authenticated via HTTP header at any time, just like normal users.
- If `allow_missing_auth_header` is `true`, anonymous requests will be treated as being requested by an anonymous account.

More detail, please see howto.

### `HTTPBasicAuth` Object

- Introduced in 1.5
- Last updated in 1.6

| Key           | Value Type | Default Value | Changed |
| ------------- | ---------- | ------------- | ------- |
| cache_type    | str        | `memory`      | v1.5    |
| cache_timeout | int        | `-1`          | v1.5    |

#### `cache_type` allowed value

- `bypass`
- `memory`
- `expiring`

#### `cache_timeout`

- Unit: second
- Supported `cache_type`:
  - `expiring`

| Value | Meaning                                |
| ----- | -------------------------------------- |
| -1    | cache does not expire (default)        |
| 0     | cache is disabled                      |
| >0    | seconds until each cache entry expires |

### `HTTPDigestAuth` Object

- Introduced in 0.7
- Last updated in 0.9

| Key          | Value Type | Default Value |
| ------------ | ---------- | ------------- |
| enable       | bool       | `false`       |
| enable_rule  | str        | ``            |
| disable_rule | str        | `neon/`       |

- When `enable` is `true`, the `disable_rule` is valid
- When `enable` is `false`, the `enable_rule` is valid

## for URL Mapping

### `Provider` Object

- Introduced in 0.1
- Last updated in 1.6

| Key                   | Value Type | Default Value |
| --------------------- | ---------- | ------------- |
| prefix                | str        | -             |
| uri                   | str        | -             |
| type                  | str        | `""`          |
| home_dir              | bool       | `false`       |
| read_only             | bool       | `false`       |
| ignore_property_extra | bool       | `true`        |

- When `read_only` is `true`; it is a read only directory, include subdirectories.
- When `ignore_property_extra` is `true`; The Provider ignores the extra property, based on the Provider's implementation.

### Provider Type

- Some providers require a `type` to ensure proper identification. eg: `webhdfs`

| Provider           | Type      | Required |
| ------------------ | --------- | -------- |
| FileSystemProvider | `fs`      | -        |
| MemoryProvider     | `memory`  | -        |
| WebHDFSProvider    | `webhdfs` | +        |

### Home Directory

- When `home_dir` is `true`, it is the home directory. The `prefix` recommends using `/~` or `/home`.
- When `home_dir` is `true` and `prefix` is `/~` and `uri` is `file:///data/homes` and `username` is `user_x`
  ; `http://webdav.host/~/path` will map to `file:///data/homes/user_x/path`.

## for Rules Process

### `HideFileInDir` Object

- Introduced in 1.0
- Last updated in 1.0

| Key                  | Value Type | Default Value | Example                                                                                                                               |
| -------------------- | ---------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| enable               | bool       | `true`        | -                                                                                                                                     |
| enable_default_rules | bool       | `true`        | -                                                                                                                                     |
| user_rules           | dict       | `{}`          | [`like default`](https://github.com/rexzhang/asgi-webdav/blob/231c233df58456e81b7264a65c1bce7d37047d19/asgi_webdav/constants.py#L326) |

### `GuessTypeExtension` Object

- Introduced in 0.4
- Last updated in 0.4

| Key                    | Value Type     | Default Value | Example                    |
| ---------------------- | -------------- | ------------- | -------------------------- |
| enable                 | bool           | `true`        | -                          |
| enable_default_mapping | bool           | `true`        | -                          |
| filename_mapping       | dict[str, str] | `{}`          | `{"README": "text/plain"}` |
| suffix_mapping         | dict[str, str] | `{}`          | `{".md": "text/plain"}`    |

### `TextFileCharsetDetect` Object

- Introduced in 0.5
- Last updated in 0.5

| Key     | Value Type | Default Value |
| ------- | ---------- | ------------- |
| enable  | bool       | `false`       |
| default | str        | `"utf-8"`     |

## for Response

### `Compression` Object

- Introduced in 0.5
- Last updated in 1.6

| Key                    | Value Type       | Default Value | Changed | Example                           |
| ---------------------- | ---------------- | ------------- | ------- | --------------------------------- |
| enable                 | bool             | `true`        | v1.6    | -                                 |
| enable_gzip            | bool             | `true`        | v0.5    | -                                 |
| enable_zstd            | bool             | `true`        | v0.5    | -                                 |
| level                  | DAVCompressLevel | `"recommend"` | v0.5    | `"fast"`/`"recommend"`/`"best"`   |
| content_type_user_rule | str              | `""`          | v0.5    | `"^application/xml$&#124;^text/"` |

#### `CompressLevel` Object

- Introduced in 0.5
- Last updated in 1.7

| DAVCompressLevel | Gzip Level | Zstd Level |
| ---------------- | ---------- | ---------- |
| fast             | 1          | 1          |
| recommend        | 4          | 3          |
| best             | 9          | 19         |

### `CORS` Object

- Introduced in 1.1
- Last updated in 1.1

| Key                | Value Type | Default Value | Example                                                 |
| ------------------ | ---------- | ------------- | ------------------------------------------------------- |
| enable             | bool       | `false`       | -                                                       |
| allow_url_regex    | str        | `None`        | `^/cors/path`                                           |
| allow_origins      | list[str]  | `[]`          | `["*"]` or `["https://example.com","http://localhost"]` |
| allow_origin_regex | str        | `None`        | `^https://.*\.example\.com$`                            |
| allow_methods      | list[str]  | `["GET"]`     | -                                                       |
| allow_headers      | list[str]  | `[]`          | `["*"]` or `["I-Am-Example-Header,"Me-Too"]`            |
| allow_credentials  | bool       | `false`       | -                                                       |
| expose_headers     | list[str]  | `[]`          | -                                                       |
| preflight_max_age  | int        | `600`         | -                                                       |

### `logging` Object

- Introduced in 1.4
- Last updated in 1.4

| Key              | Value Type | Default Value |
| ---------------- | ---------- | ------------- |
| enable           | bool       | `true`        |
| level            | str        | `"INFO"`      |
| display_datetime | bool       | `true`        |
| use_colors       | bool       | `true`        |
