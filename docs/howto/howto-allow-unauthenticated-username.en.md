# How to Allow Unauthenticated Username

To enable unauthenticated (anonymous) access, update your`json`config file like below:

```json
{
  "unauthenticated_username": "nobody",
  "account_mapping": [
    {
      "username": "nobody",
      "password": "",
      "permissions": ["+^/public"]
    }
  ]
}
```

* When `unauthenticated_username` is set, and a user with that name exists in `account_mapping`
(with an empty password), any request without authentication will be treated as this user.
* The `permissions` field controls which paths are accessible to unauthenticated users.

Tip: To disable write access, combine with "read_only": true in the corresponding provider mapping.

