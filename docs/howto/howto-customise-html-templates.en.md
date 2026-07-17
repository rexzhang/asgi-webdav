# How to customise HTML templates

## Directory browser

Create a directory with your custom templates:

```shell
mkdir -p my-templates/dir_browser
```

Copy the bundled template you want to customise (or create from scratch):

```shell
# find bundled templates in your installed package
python -c "import asgi_webdav; print(asgi_webdav.__path__[0])"
# → e.g. /usr/lib/python3.12/site-packages/asgi_webdav

cp /usr/lib/python3.12/site-packages/asgi_webdav/templates/dir_browser/index.html my-templates/dir_browser/
```

Edit `my-templates/dir_browser/index.html`. Available variables:

- `$path` — current directory path
- `$parent_html` — rendered parent row HTML (empty at root)
- `$items_html` — rendered directory/file rows HTML
- `$version` — server version string
- `$current_time` — current server time

Start the server with your custom directory:

```shell
python -m asgi_webdav --template-dir ./my-templates
```

Or via config file (`webdav.toml`):

```toml
template_dir = "/path/to/my-templates"
```

Or via environment variable:

```shell
WEBDAV_TEMPLATE_DIR=/path/to/my-templates python -m asgi_webdav
```

## 401 error page

```shell
mkdir -p my-templates/error
```

Create `my-templates/error/401.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Access Denied</title></head>
<body>
  <h1>401 Unauthorized</h1>
  <p>$message</p>
  <a href="/">Back to home</a>
</body>
</html>
```

## Admin pages

```shell
mkdir -p my-templates/admin
```

Create `my-templates/admin/index.html`:

```html
<!DOCTYPE html>
<html>
<head><title>Admin</title></head>
<body>
  <h1>Server Administration</h1>
  <a href="/_/admin/logging">View Logs</a>
</body>
</html>
```

## Partial customisation

You only need to override the files you want to change. For example, to customise only the 401 page while keeping all other templates as bundled:

```shell
mkdir -p my-templates/error
# create my-templates/error/401.html with your custom content
python -m asgi_webdav --template-dir ./my-templates
```

All other templates (directory browser, admin pages) will use the bundled defaults.

## CSS styling

The directory browser stylesheet is served as a static file via `/_/static/styles.css`. To customise it, place your own `styles.css` in `my-templates/dir_browser/`:

```shell
cp my-custom.css my-templates/dir_browser/styles.css
```

The server serves files from your custom directory first, falling back to the bundled `styles.css`.
