"""Workspace memory encryption at rest"""

from __future__ import annotations


import click


from .. import root as _root
from ..root import (
    _quiet_print,
    _sdk_client,
    cli,
    print_json,
)

# ===================================================================
# encryption commands
# ===================================================================


@cli.group()
def encryption() -> None:
    """Manage workspace memory encryption at rest.

    AES-256-GCM encryption for memory content and summary fields.
    Encrypts before writing to SpacetimeDB (which does not support
    native encryption at rest).
    """


@encryption.command(name="init")
@click.argument("workspace_id")
def encryption_init(workspace_id: str) -> None:
    """Initialise encryption for a workspace (generates a new AES-256 key).

    After init, all NEW memories will be encrypted.  Existing plaintext
    memories are NOT automatically encrypted — run ``stmem encryption
    encrypt-existing <workspace>`` to encrypt them.

    Idempotent: fails if encryption is already initialised.
    """
    client = _sdk_client()
    with _root.console.status(f"Initialising encryption for workspace '{workspace_id[:16]}...'..."):
        client.init_workspace_encryption(workspace_id)
    _quiet_print(f"[green]Encryption initialised for workspace '{workspace_id[:16]}...'.[/green]")


@encryption.command(name="enable")
@click.argument("workspace_id")
def encryption_enable(workspace_id: str) -> None:
    """Enable encryption for a workspace (requires init first)."""
    client = _sdk_client()
    with _root.console.status(f"Enabling encryption for workspace '{workspace_id[:16]}...'..."):
        client.set_workspace_encryption_enabled(workspace_id, True)
    _quiet_print(f"[green]Encryption enabled for workspace '{workspace_id[:16]}...'.[/green]")


@encryption.command(name="disable")
@click.argument("workspace_id")
def encryption_disable(workspace_id: str) -> None:
    """Disable encryption for a workspace.

    New memories will be stored as plaintext.  Existing encrypted
    memories remain encrypted.
    """
    client = _sdk_client()
    with _root.console.status(f"Disabling encryption for workspace '{workspace_id[:16]}...'..."):
        client.set_workspace_encryption_enabled(workspace_id, False)
    _quiet_print(f"[green]Encryption disabled for workspace '{workspace_id[:16]}...'.[/green]")


@encryption.command(name="rotate")
@click.argument("workspace_id")
def encryption_rotate(workspace_id: str) -> None:
    """Rotate the encryption key for a workspace.

    New memories use the new key.  Run ``stmem encryption encrypt-existing``
    after rotation to re-encrypt existing memories.
    """
    client = _sdk_client()
    with _root.console.status(f"Rotating encryption key for workspace '{workspace_id[:16]}...'..."):
        client.rotate_workspace_encryption_key(workspace_id)
    _quiet_print(f"[green]Encryption key rotated for workspace '{workspace_id[:16]}...'.[/green]")


@encryption.command(name="encrypt-existing")
@click.argument("workspace_id")
def encryption_encrypt_existing(workspace_id: str) -> None:
    """Encrypt all unencrypted existing memories in a workspace.

    Useful after initial setup or key rotation.  Encrypts memories that
    were stored before encryption was enabled, or that were created with
    a previous key.
    """
    client = _sdk_client()
    with _root.console.status(f"Encrypting existing memories in workspace '{workspace_id[:16]}...'..."):
        client.encrypt_existing_memories(workspace_id)
    _quiet_print(f"[green]Existing memories encrypted for workspace '{workspace_id[:16]}...'.[/green]")


@encryption.command(name="decrypt-memory")
@click.argument("memory_id")
def encryption_decrypt_memory(memory_id: str) -> None:
    """Fetch a single memory with its content and summary decrypted."""
    client = _sdk_client()
    with _root.console.status(f"Fetching decrypted memory '{memory_id[:16]}...'..."):
        client.get_decrypted_memory(memory_id)
    # Read results from the public decrypted_memory_result table
    rows = client._sql(
        f"SELECT content, summary, confidence, memory_type, is_active, "
        f"created_at, tier FROM decrypted_memory_result "
        f"WHERE memory_id = '{memory_id}'"
    )
    if rows:
        print_json(rows[0])
    else:
        _quiet_print(f"[yellow]No decrypted result found for memory '{memory_id[:16]}...'.[/yellow]")
