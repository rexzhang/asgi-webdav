# Anonymous User Howto

- An anonymous account is also an account, with the username/password/permissions determined by the `config.anonymous.user` configuration.
- Anonymous accounts can login by the auth header.
- By default, if the auth header is missing, the client will automatically login as an anonymous account.
- By default, anonymous users have access to all paths.

## To enable anonymous user access, update your config file like below

### just enable anonymous user

```toml
[anonymous]
enable = true
```

### customize anonymous user

```toml
[anonymous]
enable = true

[anonymous.user]
username = "anonymous"
password = ""
permissions = ["+^/$"] # Only the root directory is allowed to be accessed.
```

### more config

```toml
[anonymous]
enable = true
allow_missing_auth_header = false # If false, anonymous users can only authenticate by the auth header.

[anonymous.user]
username = "anonymous"
password = ""
permissions = ["+^/$"]
```
