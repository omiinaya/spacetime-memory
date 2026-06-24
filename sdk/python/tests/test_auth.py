"""Tests for auth.py — JWT token generation."""

import pytest
from unittest.mock import patch, Mock


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

        with patch("spacetime_memory.auth.pyjwt", mock_jwt), \
             patch("pathlib.Path.read_text", return_value="--PRIVATE KEY--"), \
             patch("spacetime_memory.auth._generate_identity",
                   return_value="c200" + "a" * 62):
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

        with patch("spacetime_memory.auth.pyjwt", mock_jwt), \
             patch("pathlib.Path.read_text", return_value="key-data"), \
             patch("spacetime_memory.auth._generate_identity",
                   return_value="c200" + "c" * 62) as mock_gen:
            token = generate_token("/fake/key.pem")

            mock_gen.assert_called_once()
            assert token == "auto.token"

    def test_path_is_cast_to_pathlib(self):
        """private_key_path can be a string."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "str-path.token"

        with patch("spacetime_memory.auth.pyjwt", mock_jwt), \
             patch("pathlib.Path.read_text", return_value="pem-data"), \
             patch("spacetime_memory.auth._generate_identity",
                   return_value="c200" + "d" * 62):
            token = generate_token("just/a/string/path.pem",
                                   identity_hex="c200" + "e" * 62)
            assert token == "str-path.token"

    def test_token_payload_structure(self):
        """Verify payload fields are passed to pyjwt.encode."""
        from spacetime_memory.auth import generate_token

        mock_jwt = Mock()
        mock_jwt.encode.return_value = "payload.token"
        ident = "c200" + "f" * 62

        with patch("spacetime_memory.auth.pyjwt", mock_jwt), \
             patch("pathlib.Path.read_text", return_value="key-material"):
            generate_token("/k.pem", identity_hex=ident, expires_in=42)

            args, kwargs = mock_jwt.encode.call_args
            payload = args[0]
            assert payload["sub"] == ident
            assert payload["iss"] == ident
            assert payload["exp"] - payload["iat"] == 42
