docker container stop asgi-webdav
docker container rm asgi-webdav
docker image rm asgi-webdav

docker build -t ray1ex/asgi-webdav .
# shellcheck disable=SC2046
docker rmi -f $(docker images -qa -f "dangling=true")

docker run -dit -p 0.0.0.0:8000:80 -v /tmp/webdav:/data -e LOGGING_LEVEL=DEBUG  --name asgi-webdav ray1ex/asgi-webdav
