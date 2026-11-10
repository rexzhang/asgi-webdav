# Protect your password in the configuration file

```json
{
  "account_mapping": [
    { "username": "user-raw", "password": "password", "permissions": ["+"] },
    {
      "username": "user-hashlib",
      "password": "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
      "permissions": ["+^/$"]
    },
    {
      "username": "user-digest",
      "password": "<digest>:ASGI-WebDAV:c1d34f1e0f457c4de05b7468d5165567",
      "permissions": ["+^/$"]
    },
    {
      "username": "user-ldap",
      "password": "<ldap>#1#ldaps://your.ldap.server.com#SIMPLE#uid=user-ldap,cn=users,dc=your.ldap.server.com",
      "permissions": ["+^/$"]
    },
    {
      "username": "*ldap",
      "password": "<ldap>#2#ldaps://your.ldap.server.com#cert_policy=try#uid={username},cn=users,dc=your.ldap.server.com",
      "permissions": ["+^/$"]
    }
  ]
}
```

## Raw Mode

user `user-raw`'s password is real password

## hashlib Mode

`password`'s format is `"<hashlib>:{algorithm}:{salt}:{hashed-password}"`

### {algorithm}

A list of supported `{algorithms}` can be found at [Python's docs](https://docs.python.org/3.11/library/hashlib.html)

The commonly used algorithms:

- sha256
- sha384
- sha512
- blake2b (optimized for 64-bit platforms)
- blake2s (optimized for 8- to 32-bit platforms)

### {salt}

`{salt}` can be any string

### {hashed-password}

`{hashed-password}`'s format is `ALGORITHM(bytes("{salt}:{password}")).hexdigest()`

example:

- {algorithm}: sha256
- {salt}: `salt`
- {password}: `password`

```text
>>> import hashlib
>>> hashlib.new("sha256", "{}:{}".format("salt", "password").encode("utf-8")).hexdigest()
'291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b'
```

### Ref

- <https://en.wikipedia.org/wiki/Comparison_of_cryptographic_hash_functions>

## HTTP Digest Mode

`password`'s format is `<digest>:{realm}:{HA1}`

### {realm}

`ASGI-WebDAV`

### {HA1}

`{HA1}`'s format is `md5(bytes("{username}:{realm}:{password}")).hexdigest()`

example:

- {username}: `user-digest`
- {realm}: `ASGI-WebDAV`
- {password}: `password`

```text
>>> import hashlib
>>> hashlib.new("md5", "{}:{}:{}".format("user-digest", "ASGI-WebDAV", "password").encode("utf-8")).hexdigest()
'c1d34f1e0f457c4de05b7468d5165567'
```

### Ref

- [RFC2617](https://datatracker.ietf.org/doc/html/rfc2617)

## LDAP(v1) (experimental)

### password format

```text
"<ldap>#1#{ldap-uri}#{mechanism}#{ldap-user}"
```

### {ldap-uri}

Example:

`ldap://your.ldap.server.com` `ldaps://your.tls.ldap.server.com`

- [Official Website](https://ldap.com/ldap-urls/)
- [RFC4516](https://docs.ldap.com/specs/rfc4516.txt)

### {mechanism}

Example:

`SIMPLE` ...

### {ldap-user}

Example:

`uid=you-name,cn=users,dc=ldap,dc=server,dc=com`

## LDAP(v2)

### username

Use `"*ldap"` as `username`

### password format

```text
"<ldap>#2#ldaps://{ldap-uri}#{params}#{user-dn-pattern}"
```

### permissions

!!! WARNING

    `permissions` will be automatically applied to all ldap accounts.

### {ldap-uri}

Example:

`ldap://your.ldap.server.com` `ldaps://your.tls.ldap.server.com`

#### Ref

- [Official Website](https://ldap.com/ldap-urls/)
- [RFC4516](https://docs.ldap.com/specs/rfc4516.txt)

### {params}

This is a query string specifying additional optional settings. Only one is supported as of now:

`cert_policy` indicates the policy about server verification. The allowed values are:

- `try` or `demand`: The server cert will be verified, and if it fais, an error will be raised. This is the default.
- `never` or `allow`: The server cert will be used without any verification.

Example:

`cert_policy=try`

#### Ref

- [RFC1866](https://datatracker.ietf.org/doc/html/rfc1866)

### {user-dn-pattern}

Specify the user DN pattern, with a `username` substitution field. Example:

`uid={username},cn=users,dc=ldap,dc=server,dc=com`

## OIDC (OpenID Connect) Bearer Auth

### username

Use `"*oidc"` as `username`. This is a sentinel entry: its password holds the OIDC IdP configuration that enables Bearer auth, and its `permissions` are the **default permissions of OIDC users** that have no account of their own (see [Account mapping](#account-mapping)), like `*ldap` for LDAP users.

- `"permissions": []` disables the fallback: only OIDC users with a configured account can log in.
- It must not set `admin: true`, the server refuses to start if it does (otherwise every OIDC user would become admin).
- It can never be used to log in: Basic and Digest auth with the username `*oidc` always fail, and Bearer tokens whose `preferred_username` starts with `*` are rejected.

### password format

```text
"<oidc>#1#{issuer}#{jwks_uri}#{audience}#{client_id}#{algorithm}#{scope}"
```

The fields are separated by `#`, so no value may contain a `#` (OIDC issuers and JWKS URIs never contain a URL fragment). A wrong number of fields is rejected at startup.

!!! NOTE

    Earlier development builds had a 9th `{group_prefix}` field. It no longer exists, a password that still contains it is rejected at startup.

All values are validated when the server starts, a configuration error prevents the server from starting rather than failing later on requests.

### {issuer}

The OIDC issuer URL. This must exactly match the `iss` claim in the JWT access token (including any trailing `/`).

Example:

`https://idp.example.com/realms/PIC`

### {jwks_uri}

The JWKS (JSON Web Key Set) endpoint URL. The server fetches the IdP's public keys from this endpoint to verify JWT signatures locally.

Example:

`https://idp.example.com/realms/PIC/protocol/openid-connect/certs`

!!! WARNING "HTTPS is required in production"

    `{issuer}` and `{jwks_uri}` must be `http://` or `https://` URLs. Plain `http://` is accepted so that a local IdP can be used for development and testing, but it logs a warning at startup.

    In production always use `https://`: over plain HTTP a network attacker can replace the JWKS with their own keys and forge tokens for any user.

### {audience}

The expected `aud` (audience) claim in the JWT. Must match the audience configured in your IdP for the client application. Must not be empty.

Example:

`account`

### {client_id}

The expected `azp` (authorized party) claim in the JWT. Must match the OAuth2 client ID configured in your IdP. Must not be empty.

Example:

`cosmohub-test`

### {algorithm}

The JWT signing algorithm used by your IdP. Must be a single algorithm (not a list). Because the keys come from a JWKS, only asymmetric algorithms are accepted:

`RS256`, `RS384`, `RS512`, `PS256`, `PS384`, `PS512`, `ES256`, `ES384`, `ES512`, `EdDSA`

`none` and the HMAC algorithms (`HS256`, ...) are rejected at startup.

### {scope}

The required scope. The JWT's `scope` claim (space-separated string) must contain this value. Must not be empty.

Example:

`openid`

### Account mapping

Any user the IdP (Keycloak) authenticates can present a token, whatever groups it belongs to. A verified Bearer token is mapped to an account by its `preferred_username` claim:

1. `preferred_username` must be a non-empty string that does not start with `*`, otherwise the request is rejected with HTTP 401.
2. If an account with exactly that `username` is configured in `account_mapping`, the request gets **that account's** permissions and `admin` flag.
3. Otherwise the user **inherits the `*oidc` permissions** (never `admin`), with `preferred_username` as its username.
4. If `*oidc` has no permissions (`[]`), the fallback is disabled and the request is rejected with HTTP 401.

No other token claim is used, in particular Keycloak groups never grant or restrict permissions.

| Account for `preferred_username` | `*oidc` permissions | Result |
| -------------------------------- | ------------------- | ------ |
| configured                       | any                 | the account's permissions |
| not configured                   | not empty           | the `*oidc` permissions |
| not configured                   | `[]`                | HTTP 401 |

!!! WARNING

    With the fallback enabled, **every** user of the realm who can get a token for `{client_id}` can log in with the `*oidc` permissions, whatever its Keycloak groups. Keep these permissions as narrow as possible; with the WebHDFS provider, HDFS still limits each user to its own storage permissions (see [Two permission layers](#two-permission-layers-webhdfs)).

#### Keycloak groups

Keycloak groups are not used by ASGI-WebDAV. Group membership is not required to authenticate, and the token's `groups` claim is never read, so it can neither grant nor restrict permissions.

#### Shared (group-like) access

Access that several people or applications share is provided by **dedicated accounts**, not by groups:

1. Create a dedicated user in HDFS with permissions on the shared paths.
2. Configure an account with the same `username` in `account_mapping`, with a password (preferably in [hashlib Mode](#hashlib-mode)) and the matching WebDAV `permissions`.
3. Users or applications that need those paths log in to that account with **HTTP Basic auth**.

These dedicated accounts do not authenticate through OIDC.

#### Two permission layers (WebHDFS)

With the [WebHDFS provider](../reference/provider/webhdfs.en.md), every HDFS request is made on behalf of the authenticated account (`doAs={username}`), where `username` is the matched account: the `preferred_username` for Bearer users, the login name for Basic users. Permissions are therefore enforced twice:

- **ASGI-WebDAV** checks the account's `permissions`: which paths and operations are reachable through WebDAV.
- **HDFS** enforces the storage permissions of the impersonated user, independently of ASGI-WebDAV.

A request has to pass both: an account allowed by ASGI-WebDAV can still only reach the HDFS paths its HDFS user is authorised for.

#### Security assumption: `preferred_username`

The OIDC specification does not guarantee that `preferred_username` is unique or stable. This implementation still uses it as the identity, and its security **relies on the IdP** that issues the tokens:

- `preferred_username` is unique across all users of the issuer;
- it is assigned by the identity infrastructure, users cannot choose it;
- users cannot change it afterwards, and names of removed users are not reassigned to other people.

If these guarantees do not hold (e.g. an IdP where users can edit their username), a user could obtain the permissions of another account with the same name, including admin accounts, so do not use this feature with such an IdP.

ASGI-WebDAV does not distinguish OIDC accounts from Basic auth accounts: any configured account can be matched by a token with the same `preferred_username`, and can also log in with Basic/Digest auth if it has a usable password. Both are the same identity. In particular, the names of dedicated (Basic auth) accounts must never be used as Keycloak usernames.

### Example configuration

```json
{
  "account_mapping": [
    {
      "username": "*oidc",
      "password": "<oidc>#1#https://idp.example.com/realms/PIC#https://idp.example.com/realms/PIC/protocol/openid-connect/certs#account#cosmohub-test#RS256#openid",
      "permissions": ["+^/$", "+^/user"]
    },
    {
      "username": "alice",
      "password": "secret",
      "permissions": ["+^/$", "+^/data/**"]
    },
    {
      "username": "grp-transfer",
      "password": "<hashlib>:sha256:salt:291e247d155354e48fec2b579637782446821935fc96a5a08a0b7885179c408b",
      "permissions": ["+^/$", "+^/data/transfer"]
    }
  ]
}
```

In this example:

- `*oidc` configures the OIDC provider, and its permissions (`/` and `/user...`) are the default for OIDC users without an account.
- A Bearer token with `preferred_username` `alice` gets `alice`'s own permissions, whatever Keycloak groups `alice` belongs to.
- Any other Keycloak user (e.g. `bob`) needs no account: it gets the `*oidc` permissions and, with WebHDFS, accesses HDFS as `doAs=bob`.
- `grp-transfer` is a dedicated HDFS account for shared access to `/data/transfer`. Users and applications log in to it with Basic auth and its password.

With `"permissions": []` on `*oidc`, `bob` would be rejected with HTTP 401 instead.

### How it works

1. A client sends `Authorization: Bearer <access_token>` to the WebDAV server.
2. The server verifies the JWT signature locally against the IdP's JWKS public keys.
3. The server checks the claims: `exp`, `iss`, `aud` and `sub` must be present; `iss`/`aud` must match the config, `exp` must be in the future; `azp` must equal `{client_id}`, `typ` must be `Bearer`, and the `scope` string must contain `{scope}`.
4. The `preferred_username` claim is mapped to a configured account, or to the `*oidc` permissions (see [Account mapping](#account-mapping)).
5. If anything fails, the request is rejected with HTTP 401. Malformed tokens or claims never cause an HTTP 500.

### JWKS keys and caching

- The JWKS is fetched once at startup; if it cannot be fetched the server does not start.
- After that the key set is cached for 5 minutes and then fetched again on the next Bearer request, so key rotation at the IdP is picked up without restarting the server.
- A token signed with an unknown key id (`kid`) triggers an immediate refresh, at most once every 30 seconds (PyJWT's cooldown), so random `kid` values cannot be used to flood the IdP.
- Each request to the IdP times out after 5 seconds. The fetch uses blocking I/O, so token verification runs in a worker thread and never blocks the server's event loop; concurrent fetches are serialized by PyJWT, and requests arriving meanwhile reuse the refreshed key set.
- If the IdP is unreachable when the cache expires, Bearer requests fail with HTTP 401 until it is reachable again (each attempt is bounded by the 5 second timeout). Basic/Digest auth is not affected.

### Prerequisites

Install the OIDC optional dependencies:

```shell
pip install ASGIWebDAV[oidc]
```

This installs `PyJWT` (>= 2.15.0, which includes the JWKS refresh cooldown and several security fixes) and `cryptography` for JWT verification. The JWKS endpoint must be reachable from the server at startup.

### Notes

- The `*oidc` password field is parsed only during server startup. It is never used for Basic/Digest password verification.
- The `preferred_username` claim is required. If a token is missing this claim, the request is rejected.
- **Local verification trade-off**: access tokens are verified locally against the JWKS public keys without calling the IdP server on each request. This avoids the latency and load of per-request token introspection, but means that a token revoked at the IdP (e.g. user logout, compromised credential) will remain accepted until it naturally expires. Since access tokens are typically short-lived (5–15 minutes), this window is small and acceptable for most deployments. If immediate revocation is required, consider token introspection (not currently supported) or use shorter token lifetimes.

## Compatibility

A single server can use **all** password modes simultaneously — each user in `account_mapping` has their own password format. The table below shows which authentication methods work with each password mode:

|                  | HTTP Basic auth | HTTP Digest auth | HTTP Bearer auth |
| ---------------- | --------------- | ---------------- | ---------------- |
| Raw Mode         | Y               | Y                | Y*               |
| hashlib Mode     | Y               | N                | Y*               |
| HTTP Digest Mode | Y               | Y                | Y*               |
| LDAP(v1)         | Y               | N                | Y*               |
| LDAP(v2)         | Y               | N                | N                |
| OIDC (`*oidc`)   | N               | N                | -                |

\* Bearer auth does not check the account's password: a valid token whose `preferred_username` equals the account's `username` is accepted (see [Account mapping](#account-mapping)). `*ldap` and `*oidc` are sentinels and can never be matched by a token.

HTTP Digest auth needs the plain password or its HA1 hash on the server side, so it only works for Raw and HTTP Digest mode accounts. A Digest login for any other account (hashlib, LDAP, `*ldap`, `*oidc`, or an account with an invalid password format) is always rejected; those accounts must use Basic auth (or Bearer auth, for configured OIDC identities).

Example: a server can have `alice` with a raw password (Basic/Digest/Bearer), `bob` via LDAP (Basic only), a dedicated `grp-transfer` hashlib account (Basic only), `*oidc` for Bearer auth, and an anonymous user — all at the same time.
