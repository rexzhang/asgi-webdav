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

```shell
pyinstaller --onefile --console \
    --name asgi-webdav \
    standalone.py
```

## Run It

```shell
./dist/asgi-webdav -r .
```
