#!/bin/sh

## set non-root user
usermod -o -u "$UID" runner
groupmod -o -g "$GID" runner

echo "
------------------------
User uid: $(id -u runner)
User gid: $(id -g runner)
------------------------
"

echo "prepare..."
chown -R runner:runner /data

echo "server starting..."
exec su-exec runner \
	python -m asgi_webdav \
		--host "$WEBDAV_HOST" \
		--port "$WEBDAV_PORT" \
		--config "$WEBDAV_CONFIGFILE" \
		--logging-no-display-datetime \
		--logging-no-use-colors 
