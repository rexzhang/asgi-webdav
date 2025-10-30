# Authentication

## Account Preprocessing

- If anonymous account are enabled, they will be automatically added to the list of accounts
- If can not found any account, the system will automatically add a default(admin) account.

```mermaid
flowchart TB
    START@{ shape: sm-circ, label: "Small start" }
    END@{ shape: framed-circle, label: "Stop" }
    A{{config.anonymous.enable?}}
    ADD_ANONYMOUS_ACCOUNT[Add config.anonymous.account to config.account_mapping]
    B{{config.account_mapping is empty?}}
    ADD_DEFAULT_ACCOUNT["Add default(admin) account to config.account_mapping"]

    START --> A
    A -->|True| ADD_ANONYMOUS_ACCOUNT --> B
    A -->|False| B
    B -->|True| ADD_DEFAULT_ACCOUNT --> END
    B -->|False| END
```

## Match/Check Account

```mermaid
flowchart TB
    START@{ shape: sm-circ, label: "Small start" }
    END@{ shape: framed-circle, label: "Stop" }
    HTTP_HEADER_CHECK{{Get HTTP header: authorization}}
    HTTP_AUTH[[HTTP Basic/Digest Auth Logic]]
    ALLOW_MISSING_AUTH_HEADER{{config.anonymous.enable and config.anonymous.allow_missing_auth_header?}}

    START--> HTTP_HEADER_CHECK
    HTTP_HEADER_CHECK -->|Got| HTTP_AUTH
    HTTP_HEADER_CHECK -->|None| ALLOW_MISSING_AUTH_HEADER
    HTTP_AUTH -->|match| USER_IS_X[User = X or Anonymous] --> END
    HTTP_AUTH -->|failed| 401([HTTP 401/Unauthorized])
    ALLOW_MISSING_AUTH_HEADER -->|False| 401
    ALLOW_MISSING_AUTH_HEADER -->|True| USER_IS_ANONYMOUS[User = Anonymous] --> END
```

## Anonymous Account

More detail, please see howto.
