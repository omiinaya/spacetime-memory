"""Split cli/commands/standalone.py into focused modules."""
from pathlib import Path

cmds_dir = Path("$HOME/spacetime-memory/sdk/python/spacetime_memory/cli/commands")
standalone_path = cmds_dir / "standalone.py"

content = standalone_path.read_text()
lines = content.split("\n")

# Helper functions and their assignments
# _find_spacetime_bin is used by init
# Generic helpers (parse_timestamp, etc.) are in their respective command bodies

# Find the exact boundaries for each group
# Group 1: compounder commands (overview, lint, cross-link, suggest-connections, 
#          store-answer, store-answers-batch, entity-page, update-entity-page, 
#          concept-page, comparison-page, search-entities) - lines 95-641
# Group 2: admin commands (diagnostics, health, doctor, init, _find_spacetime_bin, 
#          backup, restore, serve) - lines 643-1355
# Group 3: basic commands (completion, recommend, peer-reputation, synthesize) - lines 20-93, 1123-1179

# Module header block
HEADER = '''"""CLI commands — {name} commands."""

from __future__ import annotations

import json
from typing import Any

import click

from ..root import (
    HOST, PORT, DB, EMBEDDER_URL,
    console, _current_output_format, _quiet_mode, _no_header_mode,
    _compact_json_mode, _no_color_mode, _verbose_mode,
    _load_aliases, _save_aliases, _sdk_client, _quiet_print,
    print_table, print_json, parse_json_flag, _esc,
    ALIASES_FILE,
)

from ..root import cli
'''

# Write _compounder_commands.py - lines 95-641 (overview through search_entities)
compounder_body = "\n".join(lines[94:641])
cmds_dir.joinpath("_compounder_commands.py").write_text(
    HEADER.format(name="compounder") + "\n" + compounder_body + "\n"
)

# Write _admin_tools.py - lines 643-1355 (diagnostics through serve, including _find_spacetime_bin)
admin_body = "\n".join(lines[642:])
cmds_dir.joinpath("_admin_tools.py").write_text(
    HEADER.format(name="admin") + "\n" + admin_body + "\n"
)

# Write _basic_commands.py - lines 20-93 + 1105-1179 (completion, recommend, peer-reputation, synthesize, _find_spacetime_bin)
# Note: _find_spacetime_bin is at line 1105 which is in the admin section
# Let's include it in basic since it's used by init there, or put it in both
# Actually synthesize at line 1123 uses _find_spacetime_bin which is defined at 1105
# Let's include the rest in admin and just keep basic + compounder + admin

# For basic, include completion (20-33), recommend (35-72), peer_reputation (73-93), synthesize (1123-1179)
basic_parts = []
basic_parts.append("\n".join(lines[19:33]))  # completion
basic_parts.append("")
basic_parts.append("\n".join(lines[34:72]))  # recommend
basic_parts.append("")
basic_parts.append("\n".join(lines[72:93]))  # peer_reputation
basic_parts.append("")
basic_parts.append("\n".join(lines[1122:1179]))  # synthesize_cmd

cmds_dir.joinpath("_basic_commands.py").write_text(
    HEADER.format(name="basic") + "\n".join(basic_parts) + "\n"
)

# Keep standalone.py as the re-import hub
hub_content = '''"""CLI commands — standalone (convenience re-exports)."""

from __future__ import annotations

# Import sub-modules to register commands with the root cli group
from . import _basic_commands  # noqa: F401
from . import _compounder_commands  # noqa: F401
from . import _admin_tools  # noqa: F401
'''

standalone_path.write_text(hub_content)

# Update commands/__init__.py to NOT import standalone (since it's now just an import hub
# that would cause circular import)
cmd_init = cmds_dir / "__init__.py"
init_content = cmd_init.read_text()
# Replace 'from . import standalone' with imports of the new modules
new_init = init_content.replace(
    "from . import standalone\n",
    "from . import _basic_commands  # noqa: F401\nfrom . import _compounder_commands  # noqa: F401\nfrom . import _admin_tools  # noqa: F401\n"
)
cmd_init.write_text(new_init)

print("Files created:")
print(f"  _compounder_commands.py (compounder CLI commands)")
print(f"  _admin_tools.py (admin CLI commands)")  
print(f"  _basic_commands.py (basic CLI commands)")
print(f"  standalone.py -> re-export hub (reduced from 1356 lines)")
print(f"  commands/__init__.py updated")
