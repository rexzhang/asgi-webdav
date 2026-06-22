# WebHDFS Provider

## Overview

This provider integrates **WebHDFS** as a backend for the ASGI WebDAV server. It enables read/write access to an HDFS cluster over HTTP(S), using the [WebHDFS REST API](https://hadoop.apache.org/docs/stable/hadoop-project-dist/hadoop-hdfs/WebHDFS.html).

This implementation is **async**, based on `httpx`, and supports optional **Kerberos authentication** via `httpx-kerberos`. It supports user **impersonation** through the `doAs` query parameter when Kerberos is enabled.

---

## Features

- Full support for WebHDFS API over HTTP
- Async implementation using `httpx`
- Optional Kerberos authentication via `httpx-kerberos`
- User impersonation (`doAs`)
- Optional integration with LDAP

---

## Provider Registration

To use the WebHDFS provider, configure the `provider_mapping` in your main config:

```json
{
  "provider_mapping": [
    {
      "prefix": "/",
      "uri": "http://<namenode>:9870/webhdfs/v1",
      "type": "webhdfs"
    }
  ]
}
```

- `prefix`: Mount path in the WebDAV hierarchy.
- `uri`: Full base path to your WebHDFS root (should end with /webhdfs/v1).

## Authentication Modes

1. Unauthenticated WebHDFS will accept the user.name query parameter as-is. No verification is done.
2. Kerberos (recommended)
   If Kerberos is configured on the server and httpx-kerberos is installed:

- The WebDAV server authenticates as a Kerberos principal.
- Impersonation is performed using the doAs query parameter in each request to WebHDFS.
- Requires that the Kerberos principal has impersonation rights in HDFS.

## Dependencies

Required Python packages:

```bash
pip install ASGIWebDAV[webhdfs]

# or
pip install httpx httpx-kerberos
```

## Key Components

- WebHDFSProvider: Implements abstract provider interface.
- Redirect Handling: Handles 307 redirects issued by the NameNode.
- Impersonation Logic: Injects doAs param when Kerberos is used.
- Streaming Support: Uses `httpx`'s async streaming for large files.

## LDAP Integration (Optional)

Although not required, integrating with an LDAP server allows:

- Verifying WebDAV user identities before passing to doAs
- Mapping WebDAV usernames to Kerberos identities
- Restricting HDFS access based on LDAP groups

## Current Limitations / TODO

| Feature          | Status          | Notes                                   |
| ---------------- | --------------- | --------------------------------------- |
| `PROPPATCH`      | Not supported   | Add stub or raise `NotImplementedError` |
| Directory Quotas | Not handled     | Optional                                |
| `XAttr` / ACLs   | Not implemented | Not part of base WebDAV spec            |

Feel free to contribute PRs to improve these areas.
