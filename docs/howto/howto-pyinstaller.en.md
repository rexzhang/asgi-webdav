# How to use PyInstaller to package the project

## Installation Dependencies

```bash
pip install -r requirements.d/full.txt
pip install pyinstaller
```

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
