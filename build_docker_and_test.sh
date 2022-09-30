docker container stop asgi-webdav
docker container rm asgi-webdav
docker image rm ray1ex/asgi-webdav

docker pull python:3.10-alpine
docker build -t ray1ex/asgi-webdav . --build-arg ENV=dev

mkdir /tmp/webdav
docker run -dit --restart unless-stopped \
  -p 0.0.0.0:8000:8000 \
  -v /tmp/webdav:/data \
  -e UID=501 -e GID=20 \
  -e WEBDAV_ENV=dev \
  -e WEBDAV_LOGGING_LEVEL=DEBUG \
  --name asgi-webdav ray1ex/asgi-webdav
docker image prune -f
docker container logs -f asgi-webdav
