#!/bin/zsh

docker pull python:3.12-alpine
docker build -t cr.h.rexzhang.com/ray1ex/asgi-webdav . --build-arg ENV=rex

read -r -s -k '?Press any key to continue, push docker image...'
docker push cr.h.rexzhang.com/ray1ex/asgi-webdav

read -r -s -k '?Press any key to continue. startup container...'
docker container stop asgi-webdav
docker container rm asgi-webdav
mkdir /tmp/webdav
docker run -dit --restart unless-stopped \
  -p 0.0.0.0:8000:8000 \
  -v /tmp/webdav:/data \
  -e UID=501 -e GID=20 \
  -e DEBUG=true \
  -e WEBDAV_LOGGING_LEVEL=DEBUG \
  --name asgi-webdav cr.h.rexzhang.com/ray1ex/asgi-webdav

docker image prune -f
docker container logs -f asgi-webdav
