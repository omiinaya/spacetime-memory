"""Tests for spacetime_memory.auth — token generation and identity creation."""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from spacetime_memory import auth
from spacetime_memory.auth import _generate_identity, generate_token

# Path to test key fixture
TEST_KEY = Path(__file__).resolve().parent.parent.parent.parent / "data" / "id_ecdsa_pkcs8.pem"


class TestGenerateIdentity:
    """Test the _generate_identity helper function."""

    def test_returns_string(self):
        """_generate_identity returns a string."""
        ident = _generate_identity()
        assert isinstance(ident, str)

    def test_prefix_c200(self):
        """Identity hex starts with 'c200' prefix."""
        ident = _generate_identity()
        assert ident.startswith("c200"), f"Expected c200 prefix, got {ident[:8]}..."

    def test_correct_length(self):
        """Identity hex is 66 characters (c200 + 32 bytes hex)."""
        ident = _generate_identity()
        assert len(ident) == 66, f"Expected 66 chars, got {len(ident)}"

    def test_all_hex_after_prefix(self):
        """Characters after c200 are valid lowercase hex."""
        ident = _generate_identity()
        suffix = ident[4:]
        assert len(suffix) == 62
        assert all(c in "0123456789abcdef" for c in suffix)

    def test_deterministic_with_fixed_seed(self):
        """With os.urandom mocked, _generate_identity produces consistent output."""
        fixed_bytes = b"\x00" * 32
        import hashlib
        expected_hash = hashlib.sha256(fixed_bytes).digest()
        expected = "c200" + expected_hash.hex()[:62]

        with mock.patch("os.urandom", return_value=fixed_bytes):
            ident = _generate_identity()
        assert ident == expected

    def test_unique_on_sequential_calls(self):
        """Two sequential calls produce different identities."""
        id1 = _generate_identity()
        id2 = _generate_identity()
        assert id1 != id2

    def test_no_colon_or_dash(self):
        """Identity hex contains no separators."""
        ident = _generate_identity()
        assert ":" not in ident
        assert "-" not in ident


class TestGenerateToken:
    """Test the generate_token function with real keys and error paths."""

    def test_generates_string_with_real_key(self):
        """generate_token returns a non-empty string when given a valid key."""
        token = generate_token(str(TEST_KEY))
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_has_three_parts(self):
        """JWT has 3 dot-separated parts (header.payload.signature)."""
        token = generate_token(str(TEST_KEY))
        parts = token.split(".")
        assert len(parts) == 3, f"Expected 3 parts, got {len(parts)}"

    def test_can_decode_token(self):
        """Generated token can be decoded (without verification) to reveal claims."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        decoded = jwt.decode(token, options={"verify_signature": False})
        assert "sub" in decoded
        assert "iss" in decoded
        assert "iat" in decoded
        assert "exp" in decoded

    def test_iss_equals_sub(self):
        """SpacetimeDB v2.4+ requires 'iss' to match 'sub'."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        decoded = jwt.decode(token, options={"verify_signature": False})
        assert decoded["iss"] == decoded["sub"]

    def test_iat_is_recent(self):
        """iat (issued-at) timestamp is within 10 seconds of now."""
        import time
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        decoded = jwt.decode(token, options={"verify_signature": False})
        now = int(time.time())
        assert abs(decoded["iat"] - now) < 10

    def test_default_expiry_is_one_year(self):
        """Default expires_in gives ~1 year validity."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        decoded = jwt.decode(token, options={"verify_signature": False})
        validity = decoded["exp"] - decoded["iat"]
        # 1 year = 31536000s, allow ±60s for clock skew
        assert abs(validity - 31536000) < 60

    def test_custom_expiry(self):
        """Custom expires_in is respected."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY), expires_in=3600)
        decoded = jwt.decode(token, options={"verify_signature": False})
        validity = decoded["exp"] - decoded["iat"]
        assert abs(validity - 3600) < 10

    def test_token_verifies_with_public_key(self):
        """Token signature verifies against the corresponding public key."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        pub_key_path = TEST_KEY.with_suffix(".pub")
        if pub_key_path.exists():
            pub_key = pub_key_path.read_text()
            decoded = jwt.decode(token, pub_key, algorithms=["ES256"])
            assert "sub" in decoded

    def test_explicit_identity_hex(self):
        """Providing identity_hex uses that value in the token."""
        jwt = pytest.importorskip("jwt")
        ident = _generate_identity()
        token = generate_token(str(TEST_KEY), identity_hex=ident)
        decoded = jwt.decode(token, options={"verify_signature": False})
        assert decoded["sub"] == ident

    def test_generated_identity_is_used_when_none_passed(self):
        """When identity_hex is None, a generated identity appears in sub."""
        jwt = pytest.importorskip("jwt")
        token = generate_token(str(TEST_KEY))
        decoded = jwt.decode(token, options={"verify_signature": False})
        assert decoded["sub"].startswith("c200")
        assert len(decoded["sub"]) == 66

    def test_key_file_not_found(self):
        """Raises FileNotFoundError for non-existent key path."""
        with pytest.raises(FileNotFoundError):
            generate_token("/nonexistent/path/key.pem")

    def test_pyjwt_not_installed(self):
        """Raises ImportError when PyJWT is not available."""
        with mock.patch.object(auth, "pyjwt", None):
            with pytest.raises(ImportError, match="PyJWT is required"):
                generate_token(str(TEST_KEY))

    def test_key_path_as_pathlib(self):
        """Works with pathlib.Path as well as str."""
        token = generate_token(Path(str(TEST_KEY)))
        assert len(token) > 0


class TestAuthModuleAttributes:
    """Module-level attribute tests."""

    def test_generate_token_is_callable(self):
        """generate_token is a callable function."""
        assert callable(generate_token)

    def test_auth_module_docstring(self):
        """Module has a docstring."""
        assert auth.__doc__ is not None
        assert "JWT" in auth.__doc__

    def test_pyjwt_import_error_path(self):
        """Cover the except ImportError path (lines 20-21) when PyJWT is not installed.

        NOTE: This path is exercised in a subprocess because coverage cannot track
        the in-process import error. The subprocess test is run separately.
        In-process import manipulation with meta_path finders is unreliable
        due to Python's import caching.
        """
        import subprocess

        code = '''
import sys
import builtins

_original_import = builtins.__import__
def _block_jwt(name, *args, **kwargs):
    if name == "jwt" or name.startswith("jwt."):
        raise ImportError(f"No module named '{name}'")
    return _original_import(name, *args, **kwargs)
builtins.__import__ = _block_jwt

sys.path.insert(0, ".")
from spacetime_memory import auth
print("PYJWT_NONE:", auth.pyjwt is None)
'''
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
            timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "PYJWT_NONE: True" in result.stdout, f"Got: {result.stdout}"
