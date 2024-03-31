# Contributing

New feature, bug fix, new language, new howto, typo fix; everything is fine.  

!!! note

    issue -> discuss -> fork -> PR 

## Code

### Prepare

```shell
git clone https://github.com/rexzhang/asgi-webdav.git
cd asgi-webdav
pip install -U -r requirements/dev.txt
```

### Run Dev Server

```shell
python -m asgi_webdav --dev
```

## Documentation

### Create a new language translation

#### Example

```shell
cp docs/index.en.md docs/index.ru.md
```

#### Update MkDocs's config file

`mkdocs.txt` example

```yaml
      languages:
        en: English
        ru: русский
        zh: 中文
      nav_translations:
        zh:
          Home: 首页
          Setup: 配置
          Reference: 资料
          Trouble Shooting: 故障处理
```

#### Ref

- [ISO 639-1 language code](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes)
- [MkDocs's i18n plugin](https://github.com/ultrabug/mkdocs-static-i18n)

### Create a new howto

```shell
nano docs/howto/howto-this-is-a-new-howto.en.md
```

### Preview

```shell
pip install -U -r requirements/mkdocs.txt
mkdocs serve
```
