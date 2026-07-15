import pytest

pytest.importorskip("jwt", reason="OIDC extra (PyJWT) not installed")
pytest.importorskip("cryptography", reason="OIDC extra (cryptography) not installed")
