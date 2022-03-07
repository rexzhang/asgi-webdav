# How to hide files in directory with the specified client

## Hide `*.do-not-display-at-every` in all client

```json
{
  "hide_file_in_dir": {
    "user_rules": {
      "": ".+\\.do-not-display-at-every$"
    }
  }
}
```

## Hide `hide.*` and `*.hide` in macOS finder
```json
{
  "hide_file_in_dir": {
    "user_rules": {
      "WebDAVFS": "^hide\\.|.+\\.hide$"
    }
  }
}
```