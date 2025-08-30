# How to Allow Anonymous User

## To enable anonymous user access, update your config file like below

```json
{
  "account_mapping": [
    {
      "username": "anonymous",
      "password": "",
      "permissions": ["+^/public"]
    }
  ],
  "anonymous_username": "anonymous"
}
```

- When `anonymous_username` is set and a user with that name exists in `account_mapping`
  (typically with an empty password), requests with no authentication will be mapped to that user. Permissions of that user will determine allowed access for anonymous user.
- The `permissions` field controls which paths are accessible to anonymous user.
- Allow only one user to be set as an anonymous user

## Tips

- To disable write access, combine with "read_only": true in the corresponding provider mapping.
- `anonymous` is comonnly used as the anonymous username, but you can use any other name; like `nobody`
  or `guest`.
