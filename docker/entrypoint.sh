#!/bin/sh

# for dev
if [ "$DEBUG" = "true" ]; then exec python; fi

if [ "$1" == "asgi_webdav" ]; then

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

	if [ -z "$WEBDAV_HOST" ]; then
		WEBDAV_HOST="0.0.0.0"
	fi

	if [ -z "$WEBDAV_PORT" ]; then
		WEBDAV_PORT="8000"
	fi

	if [ -z "$WEBDAV_CONFIGFILE" ]; then
		WEBDAV_CONFIGFILE="/data/webdav.json"
	fi

	exec su-exec runner \
		python -m asgi_webdav \
			--host "$WEBDAV_HOST" \
			--port "$WEBDAV_PORT" \
			--config "$WEBDAV_CONFIGFILE" \
			--logging-no-display-datetime \
			--logging-no-use-colors 

fi

exec $*