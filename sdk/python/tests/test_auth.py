"""Tests for auth.py — JWT token generation."""

from unittest.mock import Mock, patch

import pytest

# ── _generate_identity ───────────────────────────────────────────────────────


class TestGenerateIdentity:
    """_generate_identity() — random SpacetimeDB-compatible identity."""

    def test_returns_valid_format(self):
        from spacetime_memory.auth import _generate_identity

        ident = _generate_identity()
        assert ident.startswith("c200")
        assert len(ident) == 66
        assert all(c in "0123456789abcdef" for c in ident)

    def test_idempotent_format(self):
        from spacetime_memory.auth import _generate_identity

        a = _generate_identity()
        b = _generate_identity()
        # Random, so almost certainly different
        assert len(a) == len(b) == 66
        assert a.startswith("c200")
        assert b.startswith("c200")


# ── generate_token ───────────────────────────────────────────────────────────


class TestGenerateToken:
    """generate_token() — JWT token creation."""

    def test_generates_token_with_pyjwt(self):
        """With pyjwt available, produces a signed token."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "fake.jwt.token"

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="--PRIVATE KEY--"),
            patch("spacetime_memory.auth._generate_identity", return_value="c200" + "a" * 62),
        ):
            token = generate_token("/fake/key.pem", identity_hex="c200b" * 13 + "bb")

            assert token == "fake.jwt.token"
            mock_jwt.encode.assert_called_once()
            args, kwargs = mock_jwt.encode.call_args
            assert args[1] == "--PRIVATE KEY--"
            assert kwargs["algorithm"] == "ES256"

    def test_raises_when_pyjwt_missing(self):
        """ImportError when pyjwt is not installed."""
        from spacetime_memory import auth

        with patch.object(auth, "pyjwt", None):
            with pytest.raises(ImportError, match="PyJWT is required"):
                auth.generate_token("/fake/key.pem")

    def test_auto_generates_identity_when_none(self):
        """When identity_hex is None, _generate_identity is called."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "auto.token"

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="key-data"),
            patch(
                "spacetime_memory.auth._generate_identity", return_value="c200" + "c" * 62
            ) as mock_gen,
        ):
            token = generate_token("/fake/key.pem")

            mock_gen.assert_called_once()
            assert token == "auto.token"

    def test_path_is_cast_to_pathlib(self):
        """private_key_path can be a string."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "str-path.token"

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="pem-data"),
            patch("spacetime_memory.auth._generate_identity", return_value="c200" + "d" * 62),
        ):
            token = generate_token("just/a/string/path.pem", identity_hex="c200" + "e" * 62)
            assert token == "str-path.token"

    def test_token_payload_structure(self):
        """Verify payload fields are passed to pyjwt.encode."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "payload.token"
        ident = "c200" + "f" * 62

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="key-material"),
        ):
            generate_token("/k.pem", identity_hex=ident, expires_in=42)

            args, kwargs = mock_jwt.encode.call_args
            payload = args[0]
            assert payload["sub"] == ident
            assert payload["iss"] == ident
            assert payload["exp"] - payload["iat"] == 42


class TestMissingPyJWT:
    """Cover the module-level except ImportError path (lines 20-21)."""

    def test_import_error_sets_pyjwt_to_none(self):
        """When 'import jwt' fails, pyjwt is set to None (simulated via subprocess)."""
        import subprocess
        import sys

        code = """\
import sys
# Block jwt import
class Blocker:
    def find_module(self, fullname, path=None):
        if fullname == 'jwt' or fullname.startswith('jwt.'):
            return self
        return None
    def load_module(self, fullname):
        raise ImportError("Blocked for testing")
sys.meta_path.insert(0, Blocker())

# Now import auth
from spacetime_memory.auth import generate_token
import spacetime_memory.auth as auth_mod
assert auth_mod.pyjwt is None, f"Expected None, got {auth_mod.pyjwt}"
print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd="$HOME/spacetime-memory/sdk/python",
        )
        assert "OK" in result.stdout, f"Failed: {result.stderr}"


class TestGenerateTokenEdgeCases:
    """Edge case tests for generate_token() — error paths and optional args."""

    def test_key_id_in_headers(self):
        """When key_id is provided, the 'kid' header is passed to pyjwt.encode."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "kid.token"
        ident = "c200" + "g" * 62

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="pem-data"),
        ):
            generate_token("/k.pem", identity_hex=ident, key_id="abc123def456")

            args, kwargs = mock_jwt.encode.call_args
            assert kwargs["headers"].get("kid") == "abc123def456"

    def test_key_id_omitted_no_kid_header(self):
        """When key_id is not provided, no 'kid' header is passed."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "no-kid.token"
        ident = "c200" + "h" * 62

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="pem-data"),
        ):
            generate_token("/k.pem", identity_hex=ident)

            args, kwargs = mock_jwt.encode.call_args
            assert "kid" not in kwargs.get("headers", {})

    def test_file_not_found_raises(self):
        """When the key file does not exist, an OSError/FileNotFoundError is raised."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "nocare"

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", side_effect=FileNotFoundError("No such file")),
            patch("spacetime_memory.auth._generate_identity", return_value="c200" + "i" * 62),
        ):
            with pytest.raises(FileNotFoundError):
                generate_token("/nonexistent/key.pem")

    def test_expired_token_expires_in_zero(self):
        """expires_in=0 creates a token with exp == iat."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "expired.token"
        ident = "c200" + "j" * 62

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="pem-data"),
        ):
            generate_token("/k.pem", identity_hex=ident, expires_in=0)

            args, kwargs = mock_jwt.encode.call_args
            payload = args[0]
            assert payload["exp"] == payload["iat"]
            assert payload["exp"] >= 0

    def test_identity_hex_invalid_format_still_passed(self):
        """generate_token passes any string as identity — caller's responsibility."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "bad-id.token"

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="pem-data"),
        ):
            token = generate_token("/k.pem", identity_hex="bad_identity_format")
            assert token == "bad-id.token"

    def test_non_ec_key_still_encoded(self):
        """The function does not validate the key format — just passes it to pyjwt."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "non-ec.token"
        ident = "c200" + "k" * 62

        with (
            patch("spacetime_memory.auth.pyjwt", mock_jwt),
            patch("pathlib.Path.read_text", return_value="not-a-real-key"),
        ):
            token = generate_token("/k.pem", identity_hex=ident)
            args, _ = mock_jwt.encode.call_args
            assert args[1] == "not-a-real-key"
            assert token == "non-ec.token"
