# Environment Variables

## Common

| Name                 | Default Value | Config Object            |
| -------------------- | ------------- | ------------------------ |
| WEBDAV_LOGGING_LEVEL | INFO          | `Config.logging_level`   |
| WEBDAV_USERNAME      | username      | `Config.account_mapping` |
| WEBDAV_PASSWORD      | password      | `Config.account_mapping` |

## Docker Specific

| Name              | Default Value       |
| ----------------- | ------------------- |
| WEBDAV_HOST       | `0.0.0.0`           |
| WEBDAV_PORT       | `8000`              |
| WEBDAV_CONFIGFILE | `/data/webdav.json` |
