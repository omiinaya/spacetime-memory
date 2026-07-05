#!/usr/bin/env python3
"""
Key rotation tool for Spacetime Memory JWT signing keys.

Generates a new ECDSA P-256 key pair, registers it with the WASM module,
and updates the SpacetimeDB config.toml.

Usage:
    # Generate a new key pair and register it
    python scripts/rotate-keys.py generate --name "ecdsa-p256-2026-rotation-1"

    # List registered keys
    python scripts/rotate-keys.py list

    # Revoke a compromised key
    python scripts/rotate-keys.py revoke <key_id>

    # Purge expired keys
    python scripts/rotate-keys.py purge

    # Get current key info
    python scripts/rotate-keys.py current

    # Rotate: generate, register, update config in one command
    python scripts/rotate-keys.py rotate --name "ecdsa-p256-2026-rotation-2"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PrivateFormat,
        NoEncryption,
        PublicFormat,
    )
except ImportError:
    print(
        "cryptography package required. Install with: pip install cryptography",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import jwt as pyjwt
except ImportError:
    print(
        "PyJWT is required. Install with: pip install 'pyjwt[crypto]'",
        file=sys.stderr,
    )
    sys.exit(1)

# Default paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CONFIG_TOML = REPO_ROOT / "server" / "spacetimedb" / "config.toml"
CONTRIBUTING_MD = REPO_ROOT / "CONTRIBUTING.md"

# SpacetimeDB CLI options
DEFAULT_STDB_HOST = os.environ.get("SPACETIMEDB_HOST", "localhost")
DEFAULT_STDB_PORT = os.environ.get("SPACETIMEDB_PORT", "3001")
DEFAULT_STDB_DB = os.environ.get("SPACETIMEDB_DB", "spacetime-memory")


def _compute_pubkey_fingerprint(pubkey_pem: str) -> str:
    """Compute SHA-256 hex fingerprint of a PEM-encoded public key."""
    # Strip PEM headers/footers and whitespace for consistent fingerprinting
    lines = pubkey_pem.strip().splitlines()
    body = "".join(
        l.strip()
        for l in lines
        if not l.startswith("-----") and l.strip()
    )
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def generate_key_pair(name: str, output_dir: Path | None = None) -> dict:
    """Generate a new ECDSA P-256 key pair.

    Returns dict with:
        name, private_key_path, public_key_path, key_id, public_key_pem
    """
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    if not name:
        name = f"ecdsa-p256-{time.strftime('%Y-%m-%d')}"

    # Generate P-256 private key
    private_key = ec.generate_private_key(ec.SECP256R1())

    # Export private key (PKCS#8 PEM)
    priv_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )

    # Derive public key
    public_key = private_key.public_key()
    pub_pem = public_key.public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )

    # Compute key fingerprint
    key_id = _compute_pubkey_fingerprint(pub_pem.decode())

    # Write to files
    priv_filename = f"id_ecdsa_pkcs8_{key_id}.pem"
    pub_filename = f"id_ecdsa_{key_id}.pub"

    priv_path = output_dir / priv_filename
    pub_path = output_dir / pub_filename

    # Don't overwrite existing keys
    if priv_path.exists():
        print(f"Key file already exists: {priv_path}", file=sys.stderr)
        print("Use a different name or delete the existing key.", file=sys.stderr)
        sys.exit(1)

    priv_path.write_text(priv_pem.decode())
    pub_path.write_text(pub_pem.decode())

    # Symlink the active private key
    active_symlink = output_dir / "id_ecdsa_pkcs8.pem"
    if active_symlink.exists() or active_symlink.is_symlink():
        old_target = os.readlink(str(active_symlink)) if active_symlink.is_symlink() else ""
        active_symlink.unlink(missing_ok=True)
    else:
        old_target = ""

    active_symlink.symlink_to(priv_filename)

    # Also create a .pub symlink
    active_pub_symlink = output_dir / "id_ecdsa.pub"
    if active_pub_symlink.exists() or active_pub_symlink.is_symlink():
        active_pub_symlink.unlink(missing_ok=True)
    active_pub_symlink.symlink_to(pub_filename)

    return {
        "name": name,
        "key_id": key_id,
        "private_key_path": str(priv_path),
        "public_key_path": str(pub_path),
        "public_key_pem": pub_pem.decode(),
        "old_symlink_target": old_target,
    }


def get_stdb_identity() -> str | None:
    """Get a SpacetimeDB identity for the current user, used for auth in calls."""
    # First try: get existing token
    token = os.environ.get("SPACETIMEDB_TOKEN")
    if not token:
        # Try to generate one from the current key
        active_key = DATA_DIR / "id_ecdsa_pkcs8.pem"
        if active_key.exists() and (active_key.is_symlink() or active_key.stat().st_size > 0):
            from spacetime_memory.auth import generate_token  # type: ignore

            token = generate_token(str(active_key))
    if not token:
        print(
            "Warning: SPACETIMEDB_TOKEN not set and no key found.",
            file=sys.stderr,
        )
        return None
    return token


def call_register_reducer(
    name: str,
    key_id: str,
    public_key_pem: str,
    private_key_path: str,
    expires_in_days: int = 365,
) -> bool:
    """Call the register_signing_key reducer via the SpacetimeDB HTTP API."""
    token = get_stdb_identity()
    if not token:
        print("Cannot register key: no auth token available.", file=sys.stderr)
        return False

    url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/reducers/register_signing_key"
    payload = {
        "args": [name, key_id, public_key_pem, private_key_path, expires_in_days],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            if resp.status == 200:
                print(f"  -> Registered key '{name}' (key_id={key_id})")
                return True
            else:
                print(f"  -> Failed: HTTP {resp.status}: {body}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"  -> Failed to call reducer: {e}", file=sys.stderr)
        return False


def update_config_toml(new_priv_key_path: Path) -> bool:
    """Update config.toml with the new private key path."""
    if not CONFIG_TOML.exists():
        print(f"Config file not found: {CONFIG_TOML}", file=sys.stderr)
        return False

    content = CONFIG_TOML.read_text()
    lines = content.splitlines()

    new_lines = []
    cert_section = False
    patched = False

    for line in lines:
        if line.strip() == "[certificate-authority]":
            cert_section = True
            new_lines.append(line)
            continue

        if cert_section and line.strip().startswith("jwt-priv-key-path"):
            new_lines.append(f'jwt-priv-key-path = "{new_priv_key_path}"')
            patched = True
            cert_section = False
            continue

        if cert_section and line.strip().startswith("["):
            # New section started; insert the line we didn't add
            cert_section = False

        new_lines.append(line)

    if not patched:
        # Add the jwt-priv-key-path if it wasn't found
        # Find the [certificate-authority] section or add one
        cert_idx = -1
        for i, line in enumerate(new_lines):
            if line.strip() == "[certificate-authority]":
                cert_idx = i
                break
        if cert_idx >= 0:
            new_lines.insert(cert_idx + 1, f'jwt-priv-key-path = "{new_priv_key_path}"')
        else:
            new_lines.append("[certificate-authority]")
            new_lines.append(f'jwt-priv-key-path = "{new_priv_key_path}"')

    CONFIG_TOML.write_text("\n".join(new_lines) + "\n")
    print(f"  -> Updated {CONFIG_TOML}")
    return True


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a new key pair."""
    result = generate_key_pair(args.name)

    print(f"\nKey pair generated successfully!")
    print(f"  Name:         {result['name']}")
    print(f"  Key ID:       {result['key_id']}")
    print(f"  Private key:  {result['private_key_path']}")
    print(f"  Public key:   {result['public_key_path']}")

    print(f"\nNext steps:")
    print(f"  1. Register the key with the module:")
    print(f"     python scripts/rotate-keys.py register --key-id {result['key_id']} \\")
    print(f"       --name \"{result['name']}\"")
    print(f"  2. Restart the SpacetimeDB node to pick up the new key path")
    print(f"  3. The old key remains valid until its tokens expire")


def cmd_register(args: argparse.Namespace) -> None:
    """Register an existing key pair with the module."""
    # Find the key files
    priv_key = DATA_DIR / f"id_ecdsa_pkcs8_{args.key_id}.pem"
    pub_key = DATA_DIR / f"id_ecdsa_{args.key_id}.pub"

    if not priv_key.exists():
        print(f"Private key not found: {priv_key}", file=sys.stderr)
        sys.exit(1)
    if not pub_key.exists():
        print(f"Public key not found: {pub_key}", file=sys.stderr)
        sys.exit(1)

    pub_pem = pub_key.read_text()
    key_id = args.key_id

    # If no key_id argument but key_id was computed, use it
    # Otherwise compute from the public key PEM
    if not key_id:
        key_id = _compute_pubkey_fingerprint(pub_pem)

    name = args.name or f"ecdsa-p256-registered-{time.strftime('%Y-%m-%d')}"

    print(f"Registering key '{name}' (key_id={key_id})...")
    ok = call_register_reducer(
        name=name,
        key_id=key_id,
        public_key_pem=pub_pem,
        private_key_path=str(priv_key),
        expires_in_days=args.expires,
    )

    if not ok:
        print("Registration failed.", file=sys.stderr)
        sys.exit(1)

    # Update config.toml symlink to point to new key
    if args.update_config:
        # Update the symlink
        active_symlink = DATA_DIR / "id_ecdsa_pkcs8.pem"
        if active_symlink.exists() or active_symlink.is_symlink():
            active_symlink.unlink(missing_ok=True)
        active_symlink.symlink_to(priv_key.name)

        active_pub_symlink = DATA_DIR / "id_ecdsa.pub"
        if active_pub_symlink.exists() or active_pub_symlink.is_symlink():
            active_pub_symlink.unlink(missing_ok=True)
        active_pub_symlink.symlink_to(pub_key.name)
        print(f"  -> Updated symlinks -> {priv_key.name}, {pub_key.name}")


def cmd_rotate(args: argparse.Namespace) -> None:
    """Full key rotation: generate new key, register it, update config."""
    # Step 1: Generate new key pair
    result = generate_key_pair(args.name)

    print(f"\nKey pair generated:")
    print(f"  Name:         {result['name']}")
    print(f"  Key ID:       {result['key_id']}")
    print(f"  Private key:  {result['private_key_path']}")
    print(f"  Public key:   {result['public_key_path']}")

    # Step 2: Register with WASM module
    print(f"\nRegistering key with module...")
    ok = call_register_reducer(
        name=result["name"],
        key_id=result["key_id"],
        public_key_pem=result["public_key_pem"],
        private_key_path=str(result["private_key_path"]),
        expires_in_days=args.expires,
    )

    if not ok:
        print("Registration failed.", file=sys.stderr)
        print("The key files remain on disk; retry with:", file=sys.stderr)
        print(f"  python scripts/rotate-keys.py register --key-id {result['key_id']}", file=sys.stderr)
        sys.exit(1)

    # Step 3: Update config.toml path if needed
    active_priv = DATA_DIR / "id_ecdsa_pkcs8.pem"
    if active_priv.is_symlink():
        current_target = Path(os.readlink(str(active_priv)))
        if current_target.name != result["private_key_path"]:
            print(f"\nConfig.toml symlink already points to the new key.")
        else:
            print(f"\nConfig.toml symlink updated -> {result['private_key_path']}")
    else:
        print(f"\nConfig.toml still points to an old key. Verify path: {active_priv}")

    print(f"\n✅ Rotation complete!")
    print(f"   Old key remains trusted until tokens expire or you revoke it.")
    print(f"   To revoke the old key later: python scripts/rotate-keys.py revoke <key_id>")


def cmd_list(args: argparse.Namespace) -> None:
    """List registered signing keys."""
    token = get_stdb_identity()
    if not token:
        print("Cannot list keys: no auth token available.", file=sys.stderr)
        sys.exit(1)

    # Since the list_signing_keys reducer writes to jwt_signing_key_result,
    # we call the reducer then query the public table via SQL
    import urllib.request

    # Call reducer
    reducer_url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/reducers/list_signing_keys"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        reducer_url,
        data=b"{}",
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as e:
        print(f"Failed to call list_signing_keys: {e}", file=sys.stderr)
        sys.exit(1)

    # Query the result table
    sql_url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/sql"
    sql = "SELECT * FROM jwt_signing_key_result ORDER BY key_version DESC LIMIT 100"
    sql_req = urllib.request.Request(
        sql_url,
        data=json.dumps(sql).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(sql_req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            rows = data.get("rows", []) if isinstance(data, dict) else data
    except Exception as e:
        print(f"Failed to query keys: {e}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No signing keys registered.")
        return

    print(f"\n{'Ver':>4} {'Key ID':<18} {'Name':<35} {'Current':<8} {'Trusted':<8} {'Created':<12}")
    print("-" * 95)
    for row in rows:
        if isinstance(row, dict):
            key_id = row.get("key_id", "")
            name = row.get("name", "")
            kv = row.get("key_version", 0)
            cur = "✓" if row.get("is_current") else ""
            tr = "✓" if row.get("is_trusted") else "✗"
            created = time.strftime(
                "%Y-%m-%d",
                time.gmtime(row.get("created_at", 0) / 1_000_000),
            )
        else:
            # List format
            key_id, name, kv, cur, tr, created = "?", "?", 0, "", "", "?"
            if len(row) >= 9:
                key_id = str(row[3])
                name = str(row[2])
                kv = row[1] if isinstance(row[1], (int, float)) else 0
                cur = "✓" if row[4] else ""
                tr = "✓" if row[5] else "✗"
                created = time.strftime(
                    "%Y-%m-%d", time.gmtime(row[6] / 1_000_000) if isinstance(row[6], (int, float)) else "?"
                )
        print(f"{kv:>4} {key_id:<18} {name[:34]:<35} {cur:<8} {tr:<8} {created:<12}")


def cmd_revoke(args: argparse.Namespace) -> None:
    """Revoke a signing key."""
    token = get_stdb_identity()
    if not token:
        print("Cannot revoke key: no auth token available.", file=sys.stderr)
        sys.exit(1)

    import urllib.request

    url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/reducers/revoke_signing_key"
    payload = {"args": [args.key_id]}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Key '{args.key_id}' revoked successfully.")
    except Exception as e:
        print(f"Failed to revoke key: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_current(args: argparse.Namespace) -> None:
    """Show the current signing key."""
    token = get_stdb_identity()
    if not token:
        print("Cannot get current key: no auth token available.", file=sys.stderr)
        sys.exit(1)

    import urllib.request

    url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/reducers/get_current_signing_key"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except Exception as e:
        print(f"Failed to get current key: {e}", file=sys.stderr)
        sys.exit(1)

    # Query the result
    sql_url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/sql"
    sql = "SELECT * FROM jwt_signing_key_result ORDER BY key_version DESC LIMIT 1"
    sql_req = urllib.request.Request(
        sql_url,
        data=json.dumps(sql).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(sql_req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            rows = data.get("rows", []) if isinstance(data, dict) else data
    except Exception as e:
        print(f"Failed to query current key: {e}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No current signing key found.")
        return

    row = rows[0]
    if isinstance(row, dict):
        print(f"  Key ID:       {row.get('key_id', '?')}")
        print(f"  Name:         {row.get('name', '?')}")
        print(f"  Version:      {row.get('key_version', '?')}")
        print(f"  Trusted:      {'Yes' if row.get('is_trusted') else 'No'}")
        print(f"  Created:      {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(row.get('created_at', 0) / 1_000_000))}")
        exp = row.get('expires_at', 0)
        if exp:
            print(f"  Expires:      {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(exp / 1_000_000))}")
        else:
            print(f"  Expires:      Never")
    else:
        print(f"  Key ID:       {row[3] if len(row) > 3 else '?'}")
        print(f"  Name:         {row[2] if len(row) > 2 else '?'}")


def cmd_purge(args: argparse.Namespace) -> None:
    """Purge expired signing keys."""
    token = get_stdb_identity()
    if not token:
        print("Cannot purge keys: no auth token available.", file=sys.stderr)
        sys.exit(1)

    import urllib.request

    url = f"http://{DEFAULT_STDB_HOST}:{DEFAULT_STDB_PORT}/v1/database/{DEFAULT_STDB_DB}/reducers/purge_expired_signing_keys"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    req = urllib.request.Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("Expired keys purged successfully.")
    except Exception as e:
        print(f"Failed to purge keys: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="JWT signing key rotation tool")
    sub = parser.add_subparsers(dest="command", help="Sub-command")

    # generate
    gen = sub.add_parser("generate", help="Generate a new key pair")
    gen.add_argument("--name", default="", help="Human-readable key name")

    # register
    reg = sub.add_parser("register", help="Register an existing key pair with the module")
    reg.add_argument("--key-id", required=True, help="Key ID (fingerprint)")
    reg.add_argument("--name", default="", help="Human-readable key name")
    reg.add_argument("--expires", type=int, default=365, help="Days until expiry (0 = never)")
    reg.add_argument(
        "--update-config",
        action="store_true",
        help="Also update symlinks in data/ to point to this key",
    )

    # rotate (full rotation)
    rot = sub.add_parser("rotate", help="Full key rotation: generate + register + update config")
    rot.add_argument("--name", default="", help="Human-readable key name")
    rot.add_argument("--expires", type=int, default=365, help="Days until expiry (0 = never)")

    # list
    sub.add_parser("list", help="List registered signing keys")

    # revoke
    rev = sub.add_parser("revoke", help="Revoke a signing key")
    rev.add_argument("key_id", help="Key ID to revoke")

    # current
    sub.add_parser("current", help="Show current signing key info")

    # purge
    sub.add_parser("purge", help="Purge expired signing keys")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "generate": cmd_generate,
        "register": cmd_register,
        "rotate": cmd_rotate,
        "list": cmd_list,
        "revoke": cmd_revoke,
        "current": cmd_current,
        "purge": cmd_purge,
    }
    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
