# How to customise HTML templates

## Template system

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

Edit `my-templates/dir_browser/index.html` using Jinja2 syntax. Available values include:

- `path` — current directory path
- `parent` — parent row data, or `None` at the root
- `items` — directory/file presentation records
- `version` — server version string
- `current_time` — current server time

The bundled directory browser uses `{% extends "base.html" %}` and includes row
partials. You can add a footer directly to a page or customize `base.html` for a
shared footer across all pages. Missing custom files fall back independently to
the bundled templates.

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

An empty or whitespace-only `template_dir` is treated as not set, so it never
exposes the working directory through `/_/static/`.

## Startup validation and failure policy

All templates in the application manifest are parsed at startup, together with
their `extends`/`include` dependencies. A syntax error in any of them is a
failure. A dependency that cannot be found is only logged as a warning, since
`{% include ... ignore missing %}` and conditional `{% extends %}` are valid
Jinja. When a template is broken, the `template_failure_policy` setting decides
what happens:

- `fallback` (default): log the broken template and the Jinja error, discard the
  whole custom tree, and serve the bundled templates only.
- `stop`: log a critical message and exit with status 1.

```shell
python -m asgi_webdav --template-dir ./my-templates --template-failure-policy stop
```

Any other `template_failure_policy` value is rejected at startup (exit status 1)
instead of falling back, so a typo cannot disable `stop`.

The custom tree is discarded as a whole on failure; a page never mixes custom
and bundled files.

## 401 error page

```shell
mkdir -p my-templates/error
```

Create `my-templates/error/401.html` (Jinja2):

```html
<!DOCTYPE html>
<html>
<head><title>Access Denied</title></head>
<body>
  <h1>401 Unauthorized</h1>
  <p>{{ message }}</p>
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

Because a custom tree may be partial, it can silently drift after a server
upgrade. To make that visible, place the server version in an optional `VERSION`
file at the root of your template directory:

```shell
python -c "import asgi_webdav; print(asgi_webdav.__version__)" > my-templates/VERSION
```

If the version differs from the running server, startup logs a warning telling
you to review your overrides. The server still starts; the file is only an
upgrade guard.

## CSS styling

The directory browser stylesheet is served as a static file via `/_/static/dir_browser/styles.css`. To customise it, place your own `styles.css` in `my-templates/dir_browser/`:

```shell
cp my-custom.css my-templates/dir_browser/styles.css
```

The server serves files from your custom directory first, falling back to the bundled `styles.css`.
