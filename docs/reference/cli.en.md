# Command Line Interface

## Command Line Interface Args

- Introduced in 0.8
- Last updated in 1.0

```shell
python -m asgi_webdav --help
Usage: python -m asgi_webdav [OPTIONS]

  Run ASGI WebDAV server

Options:
  -V, --version              Print version info and exit.
  -H, --host TEXT            Bind socket to this host.  [default: 127.0.0.1]
  -P, --port INTEGER         Bind socket to this port.  [default: 8000]
  -c, --config TEXT          Load configuration from file.  [default: None]
  -u, --user <TEXT TEXT>...  Administrator username/password. [default:
                             username password]
  -r, --root-path TEXT       Mapping provider URI to path '/'. [default: None]
  --dev                      Enter Development mode, DON'T use it in
                             production!
  --help                     Show this message and exit.
```

## Example

```shell
python -m asgi_webdav --root-path .
2022-02-26 16:48:41,857 INFO: [asgi_webdav.server] ASGI WebDAV Server(v0.9.1) starting...
2022-02-26 16:48:41,857 INFO: [asgi_webdav.auth] Register User: username, allow:[''], deny:[]
2022-02-26 16:48:41,857 INFO: [asgi_webdav.web_dav] Mapping Prefix: / => file://.
2022-02-26 16:48:42,272 INFO: [asgi_webdav.server] ASGI WebDAV Server running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

username is `username`, password is `password`, map `.` to `http://localhost:8000`
