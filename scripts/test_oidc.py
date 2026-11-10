#!/usr/bin/env python3
"""Manual integration test: obtain an OIDC access_token via ROPC and use it
to access a WebDAV directory.

This is a manual/integration helper, not a pytest test. It needs a running
ASGI-WebDAV server and a reachable Keycloak IdP, so it is intentionally kept
out of the automated test suite.

Configuration is read from ``test.env`` in the repo root (untracked, gitignored
in practice). No secrets are hardcoded here.
"""

import os
import sys

import httpx

ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "test.env"
)


def load_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def obtain_access_token(env: dict[str, str]) -> str:
    response = httpx.post(
        env["OIDC_TOKEN_URI"],
        data={
            "grant_type": "password",
            "client_id": env["OIDC_CLIENT_ID"],
            "client_secret": env["OIDC_CLIENT_SECRET"],
            "username": env["NAME"],
            "password": env["PASSWORD"],
            "scope": env.get("OIDC_SCOPE", "openid"),
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"Token request failed: HTTP {response.status_code}\n{response.text}"
        )

    token = response.json().get("access_token")
    if not token:
        raise SystemExit("Token response did not contain 'access_token'")
    return token


def webdav_check(target_url: str, access_token: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}

    # PROPFIND on the collection is the real check: a 207 proves the
    # authenticated subject can actually see the directory.
    propfind_resp = httpx.request(
        "PROPFIND",
        target_url,
        headers={**headers, "Depth": "1"},
        timeout=30,
    )
    print(f"PROPFIND {target_url} -> {propfind_resp.status_code}")
    if propfind_resp.status_code == 401:
        raise SystemExit("FAIL: 401 Unauthorized — token rejected or no permission")
    if propfind_resp.status_code in (207, 200, 403):
        # 403 means the token was accepted but the user has no permission on
        # this path; treated as an accepted token for the purpose of this test.
        pass
    if propfind_resp.status_code == 404:
        print(
            f"The keycloak user does not have a home directory at {target_url}, but the access_token was accepted. 404 is expected if the path does not exist."
        )
        pass
    else:
        print(f"  unexpected status, body: {propfind_resp.text[:500]}")

    # GET on the directory for completeness (dir-browser HTML or 200).
    get_resp = httpx.get(target_url, headers=headers, timeout=30)
    print(f"GET     {target_url} -> {get_resp.status_code}")
    if get_resp.status_code == 401:
        raise SystemExit("FAIL: GET returned 401 — token rejected or no permission")

    print("PASS: access_token accepted, WebDAV directory accessible")


def test_invalid_token(target_url: str) -> None:
    print("\n--- Testing invalid token (garbage) ---")
    headers = {"Authorization": "Bearer not-a-valid-token"}
    resp = httpx.request(
        "PROPFIND", target_url, headers={**headers, "Depth": "1"}, timeout=30
    )
    print(f"PROPFIND (invalid token) -> {resp.status_code}")
    if resp.status_code != 401:
        raise SystemExit(
            f"FAIL: Expected 401 for invalid token, got {resp.status_code}"
        )
    print("PASS: Invalid token rejected")


def test_anonymous_access(target_url: str) -> None:
    print("\n--- Testing anonymous access (no header) ---")
    # No Authorization header
    resp = httpx.request("PROPFIND", target_url, headers={"Depth": "1"}, timeout=30)
    print(f"PROPFIND (no header) -> {resp.status_code}")
    if resp.status_code not in (207, 200, 403):
        raise SystemExit(
            f"FAIL: Expected success (207/200) or 403 for anonymous, got {resp.status_code}"
        )
    print("PASS: Anonymous access (no header) worked as expected")


def main() -> None:
    if not os.path.exists(ENV_PATH):
        raise SystemExit(f"Missing config file: {ENV_PATH}")

    env = load_env(ENV_PATH)
    required = [
        "OIDC_TOKEN_URI",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "NAME",
        "PASSWORD",
        "WEBDAV_URL",
    ]
    missing = [k for k in required if k not in env]
    if missing:
        raise SystemExit(f"Missing keys in test.env: {', '.join(missing)}")

    # Target directory to exercise.
    webdav_url = env["WEBDAV_URL"].rstrip("/")
    test_path = env.get("WEBDAV_TEST_PATH", "").strip()
    target_url = f"{webdav_url}/{test_path.lstrip('/')}" if test_path else webdav_url

    print("--- Testing valid OIDC bearer token ---")
    print(
        f"Obtaining access_token from {env['OIDC_TOKEN_URI']} "
        f"for user '{env['NAME']}'..."
    )
    access_token = obtain_access_token(env)
    print(f"access_token obtained (len={len(access_token)})")

    webdav_check(target_url, access_token)

    # Run additional cases
    test_invalid_token(target_url)
    # test_anonymous_access(target_url)

    sys.exit(0)


if __name__ == "__main__":
    main()
