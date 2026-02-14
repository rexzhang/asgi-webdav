#!/bin/sh

echo "
------------------------
App user's UID:GID

	$UID:$GID
------------------------
"

echo "prepare..."
chown -R $UID:$GID /data

echo "server starting..."
exec su-exec $UID:$GID \
	python -m asgi_webdav \
		--host "$WEBDAV_HOST" \
		--port "$WEBDAV_PORT" \
		--config "$WEBDAV_CONFIGFILE" \
		--logging-no-display-datetime \
		--logging-no-use-colors
