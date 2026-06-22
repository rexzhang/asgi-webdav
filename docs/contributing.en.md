# Contributing

New feature, bug fix, new language, new howto, typo fix; everything is fine.

> If you want to participate in this project, you are welcome to start by translating/writing documents.

## Basic principles

### Target user

- Self-hosting(as app, with docker container)
- Developers using ASGI frameworks

### User strategy

#### Normal user

- Out-of-the-box
- Guiding users to improve their configuration through log messages

#### Power user

- Flexibility should be provided without affecting the normal user

## Workflow

```mermaid
graph TD
    A[Proposal in Github Issue] -->|fork| C[PR Draft]
    C --> D[CI] --> C
    D -->|Out of Draft mode| E[review] --> C
    E --> F[merge]
```

### [Proposal](https://github.com/rexzhang/asgi-webdav/issues)

- Why/How/Who
- discuss of the technical solution

### [PR Draft](https://github.com/rexzhang/asgi-webdav/pulls)

- create PR in Draft mode
- discuss of technical details
- add/check/update unit test
- check/update document
- CI/review code(move out Draft mode)

## Coding

### Prepare

```shell
git clone https://github.com/rexzhang/asgi-webdav.git
cd asgi-webdav
pip install -U -r requirements.txt
```

### Run Dev Server

```shell
python -m asgi_webdav --dev
```

### Check commit by [pre-commit](https://pre-commit.com/)

```shell
pip install pre-commit
pre-commit install
pre-commit run -a
```

### Check by mypy

```shell
pip install -U -r requirements.d/mypy.txt
mypy
```

## Documentation

### Create a new document file

```shell
nano docs/howto/this-is-a-new-howto.en.md
```

### Preview

```shell
pip install -U -r requirements.d/mkdocs.txt
fab mkdocs
```
