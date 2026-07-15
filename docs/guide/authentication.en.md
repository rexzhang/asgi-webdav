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

The server supports three authentication methods, checked in this order:

1. **HTTP Basic Auth** — `Authorization: Basic <base64(user:password)>`
2. **HTTP Digest Auth** — `Authorization: Digest <digest-data>`
3. **HTTP Bearer Auth (OIDC)** — `Authorization: Bearer <access_token>`
4. **Anonymous** — no `Authorization` header, falls back to the anonymous user (if enabled)

```mermaid
flowchart TB
    START@{ shape: sm-circ, label: "Small start" }
    END@{ shape: framed-circle, label: "Stop" }
    HTTP_HEADER_CHECK{{Get HTTP header: authorization}}
    BASIC_AUTH{{Is Basic?}}
    DIGEST_AUTH{{Is Digest?}}
    BEARER_AUTH{{Is Bearer?}}
    BASIC_LOGIC[[Basic Auth: parse credentials, verify password]]
    DIGEST_LOGIC[[Digest Auth: verify digest response]]
    BEARER_LOGIC[[Bearer Auth: verify JWT signature + claims, extract preferred_username]]
    ALLOW_MISSING_AUTH_HEADER{{config.anonymous.enable and config.anonymous.allow_missing_auth_header?}}

    START--> HTTP_HEADER_CHECK
    HTTP_HEADER_CHECK -->|None| ALLOW_MISSING_AUTH_HEADER
    HTTP_HEADER_CHECK -->|Got| BASIC_AUTH
    BASIC_AUTH -->|Yes| BASIC_LOGIC
    BASIC_AUTH -->|No| DIGEST_AUTH
    DIGEST_AUTH -->|Yes| DIGEST_LOGIC
    DIGEST_AUTH -->|No| BEARER_AUTH
    BEARER_AUTH -->|Yes| BEARER_LOGIC
    BEARER_AUTH -->|No| 401_UNKNOWN([HTTP 401 - Unknown auth method])

    BASIC_LOGIC -->|match| USER_IS_X[User authenticated] --> END
    BASIC_LOGIC -->|failed| 401([HTTP 401/Unauthorized])
    DIGEST_LOGIC -->|match| USER_IS_X
    DIGEST_LOGIC -->|failed| 401
    BEARER_LOGIC -->|match| USER_IS_X
    BEARER_LOGIC -->|failed| 401

    ALLOW_MISSING_AUTH_HEADER -->|False| 401
    ALLOW_MISSING_AUTH_HEADER -->|True| USER_IS_ANONYMOUS[User = Anonymous] --> END
```

### Bearer Auth (OIDC)

When a client sends `Authorization: Bearer <access_token>`:

1. The JWT is verified locally against the IdP's JWKS public keys (fetched at startup).
2. Required claims are checked: `iss`, `aud`, `azp`, `typ` ("Bearer"), `scope`, `exp`.
3. The `preferred_username` claim is extracted and looked up in `account_mapping`.
4. If found, that user's permissions are used. If not found, the `*oidc` template permissions are inherited.
5. If the token is invalid or the subject is not configured, HTTP 401 is returned.

See [Protect your password](protect-your-password-in-the-config.en.md#oidc-openid-connect-bearer-auth) for configuration details.

## Anonymous Account

More detail, please see howto.
