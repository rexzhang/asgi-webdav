# Known issues

## Upgrade to 0.8.x with watchtower or portainer

please change `Container.CMD` from `uvicorn asgi_webdav.docker:app --host 0.0.0.0 --port 80 --lifespan off` to `python -m asgi_webdav --host 0.0.0.0 --port 80 --in-docker-container` manually
