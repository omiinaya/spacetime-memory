"""JWT token generation for SpacetimeDB authentication.

Generates ES256 (ECDSA P-256) tokens compatible with SpacetimeDB's
JWT authentication system.

Supports key rotation via the ``kid`` header, allowing the node to
identify which signing key was used.

Usage:
    token = generate_token("/path/to/private_key.pem")
    client = Client(..., token=token)

    # With key ID (for rotation support)
    token = generate_token("/path/to/private_key.pem", key_id="abc123def456")
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None  # type: ignore


def generate_token(
    private_key_path: str | Path,
    identity_hex: str | None = None,
    expires_in: int = 86400 * 365,  # 1 year
    key_id: str | None = None,
) -> str:
    """Generate an ES256 JWT token for SpacetimeDB authentication.

    Args:
        private_key_path: Path to the ECDSA P-256 private key (PKCS#8 PEM).
        identity_hex: The SpacetimeDB identity to authenticate as.
            If None, generates a fresh identity (c200...) using the
            same algorithm SpacetimeDB uses.
        expires_in: Token validity in seconds (default: 1 year).
        key_id: Optional key ID (``kid`` JWT header). Set this to the
            key fingerprint registered via ``register_signing_key``
            so the node can identify which signing key was used during
            key rotation. If omitted, no ``kid`` header is included.

    Returns:
        A signed JWT token string.
    """
    if pyjwt is None:
        raise ImportError(
            "PyJWT is required for token generation. Install with: pip install 'pyjwt[crypto]'"
        )

    if identity_hex is None:
        identity_hex = _generate_identity()

    private_key_pem = Path(private_key_path).read_text()

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": identity_hex,
        "iss": identity_hex,  # SpacetimeDB v2.4+ requires 'iss' claim
        "iat": now,
        "exp": now + expires_in,
    }

    headers: dict[str, str] = {}
    if key_id:
        headers["kid"] = key_id

    token = pyjwt.encode(payload, private_key_pem, algorithm="ES256", headers=headers)
    return token


def _generate_identity() -> str:
    """Generate a random SpacetimeDB-compatible identity hex.

    SpacetimeDB identities are 32-byte SHA-256 hashes with a 'c200' prefix,
    encoded as 66-character hex strings.
    """
    import os

    random_bytes = os.urandom(32)
    hash_bytes = hashlib.sha256(random_bytes).digest()
    return "c200" + hash_bytes.hex()[:62]
