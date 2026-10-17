# How to use PyInstaller to package the project

## Installation Dependencies

```bash
pip install -r requirements.d/basic.txt -r requirements.d/standalone.txt
pip install "pyinstaller>=6.21"
```

Note: the standalone build does not bundle the LDAP auth backend (bonsai) and
the WebHDFS provider (httpx/httpx-kerberos) — both need native C libraries that
are not available on every target platform. The application degrades
gracefully at runtime when they are missing.

## Build Executable File

The repository contains a committed spec file, used by the GitHub Release
workflow and local builds alike:

```shell
pyinstaller asgi-webdav.spec
```

## Spec File

To regenerate `asgi-webdav.spec`:

```shell
pyi-makespec --onefile --console --name asgi-webdav standalone.py
```

Keep the two manual fixes after regenerating — the generated defaults are
wrong for this project:

- `upx=False`: UPX breaks the code signature on macOS and causes antivirus
  false positives on Windows.
- `datas=[('asgi_webdav/static', 'asgi_webdav/static')]`: the `/_/static`
  route is served from `Path(__file__).parent/static` in
  `asgi_webdav/server.py`, so the directory must be bundled.

## Run It

```shell
./dist/asgi-webdav -r .
```
