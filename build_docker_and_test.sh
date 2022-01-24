docker container stop asgi-webdav
docker container rm asgi-webdav
docker image rm ray1ex/asgi-webdav

docker pull python:3.10-alpine
docker build -t ray1ex/asgi-webdav . --build-arg ENV=rex

mkdir /tmp/webdav
docker run -dit -p 0.0.0.0:8000:8000 -v /tmp/webdav:/data \
  -e WEBDAV_LOGGING_LEVEL=DEBUG \
  -e UID=501 -e GID=20 \
  --name asgi-webdav ray1ex/asgi-webdav
docker image prune -f
docker container logs -f asgi-webdav
