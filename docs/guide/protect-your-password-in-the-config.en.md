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

Use `"*oidc"` as `username`. This is a sentinel entry that configures the OIDC provider and serves as the default permission template for authenticated Bearer users.

### password format

```text
"<oidc>#1#{issuer}#{jwks_uri}#{audience}#{client_id}#{algorithm}#{scope}"
```

### {issuer}

The OIDC issuer URL. This must exactly match the `iss` claim in the JWT access token.

Example:

`https://idp.example.com/realms/PIC`

### {jwks_uri}

The JWKS (JSON Web Key Set) endpoint URL. The server fetches public keys from this endpoint at startup to verify JWT signatures locally.

Example:

`https://idp.example.com/realms/institution/protocol/openid-connect/certs`

### {audience}

The expected `aud` (audience) claim in the JWT. Must match the audience configured in your IdP for the client application.

Example:

`account`

### {client_id}

The expected `azp` (authorized party) claim in the JWT. Must match the OAuth2 client ID configured in your IdP.

Example:

`cosmohub-test`

### {algorithm}

The JWT signing algorithm used by your IdP. Must be a single algorithm (not a list).

Common values: `RS256`, `ES256`

### {scope}

The required scope claim. The JWT's `scope` claim (space-separated) must contain this value.

Example:

`openid`

### permissions

!!! WARNING

    `permissions` will be automatically applied to all OIDC Bearer users that are not explicitly listed in `account_mapping`.

### Example configuration

```json
{
  "account_mapping": [
    {
      "username": "*oidc",
      "password": "<oidc>#1#https://idp.example.com/realms/PIC#https://idp.example.com/realms/institution/protocol/openid-connect/certs#account#cosmohub-test#RS256#openid",
      "permissions": ["+^/$"]
    },
    {
      "username": "alice",
      "password": "secret",
      "permissions": ["+^/data/public"]
    }
  ]
}
```

In this example:

- `*oidc` configures the OIDC provider and grants default permissions `+^/$` (root only) to any authenticated Bearer user.
- `alice` is an explicitly configured user. When `alice` authenticates via Bearer, she gets `+^/data/public` permissions (more permissive than the default).
- Any other Keycloak user (e.g. `bob`) who presents a valid token inherits the `*oidc` default permissions (`+^/$`).

### How it works

1. A client sends `Authorization: Bearer <access_token>` to the WebDAV server.
2. The server verifies the JWT signature locally against the JWKS public keys (fetched at startup).
3. The server checks the required claims: `iss`, `aud`, `azp`, `typ` ("Bearer"), `scope`, and `exp`.
4. The `preferred_username` claim is extracted and looked up in `account_mapping`.
5. If found, that user's permissions are used. If not found, the `*oidc` template permissions are inherited.
6. If the token is invalid, expired, or has missing claims, the request is rejected with HTTP 401.

### Prerequisites

Install the OIDC optional dependencies:

```shell
pip install ASGIWebDAV[oidc]
```

This installs `PyJWT` and `cryptography` for JWT verification. The JWKS endpoint must be reachable from the server at startup (keys are fetched once and cached in memory).

### Notes

- The `*oidc` password field is parsed only during server startup. It is never used for Basic/Digest password verification — Basic auth against an OIDC-configured user always fails.
- JWT tokens are verified locally (no network call per request). JWKS keys are fetched once at startup; restart the server to rotate keys.
- The `preferred_username` claim is required by Keycloak. If a token is missing this claim, the request is rejected.
- **Local verification trade-off**: access tokens are verified locally against the JWKS public keys without calling the IdP server on each request. This avoids the latency and load of per-request token introspection, but means that a token revoked at the IdP (e.g. user logout, compromised credential) will remain accepted until it naturally expires. Since access tokens are typically short-lived (5–15 minutes), this window is small and acceptable for most deployments. If immediate revocation is required, consider token introspection (not currently supported) or use shorter token lifetimes.

## Compatibility

A single server can use **all** password modes simultaneously — each user in `account_mapping` has their own password format. The table below shows which authentication methods work with each password mode:

|                  | HTTP Basic auth | HTTP Digest auth | HTTP Bearer auth |
| ---------------- | --------------- | ---------------- | ---------------- |
| Raw Mode         | Y               | Y                | N                |
| hashlib Mode     | Y               | N                | N                |
| HTTP Digest Mode | Y               | Y                | N                |
| LDAP(v1)         | Y               | N                | N                |
| LDAP(v2)         | Y               | N                | N                |
| OIDC             | N               | N                | Y                |

Example: a server can have `alice` with a raw password (Basic/Digest), `bob` via LDAP (Basic only), `*oidc` for Bearer auth, and an anonymous user — all at the same time.
