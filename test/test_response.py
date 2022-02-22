from asgi_webdav.response import (
    dir_file_ignore_is_match_file_name,
    dir_file_ignore_get_rule_by_client_user_agent,
    dir_file_ignore_is_match_file_name,
)


config_data = {
    "provider_mapping": [
        {
            "prefix": "/",
            "uri": "file://.",
        },
    ],
}

MACOS_UA = "WebDAVFS/3.0.0 (03008000) Darwin/21.3.0 (x86_64)"
WINDOWS_UA = "Microsoft-WebDAV-MiniRedir/10.0.19043"


def test():
    macos_rule = dir_file_ignore_get_rule_by_client_user_agent(MACOS_UA)
    windows_rule = dir_file_ignore_get_rule_by_client_user_agent(WINDOWS_UA)

    # macOS
    assert dir_file_ignore_is_match_file_name(macos_rule, "Thumbs.db")

    # Windows
    assert dir_file_ignore_is_match_file_name(windows_rule, ".DS_Store")
    assert dir_file_ignore_is_match_file_name(windows_rule, "._.test")

    # Synology
    assert dir_file_ignore_is_match_file_name(macos_rule, "#recycle")
    assert dir_file_ignore_is_match_file_name(windows_rule, "@eaDir")
