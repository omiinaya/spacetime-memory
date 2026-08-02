"""Pytest configuration for integration tests."""
import sys
from pathlib import Path

# Ensure the SDK is importable
_sdk_path = str(Path(__file__).resolve().parent.parent / "sdk" / "python")
if _sdk_path not in sys.path:
    sys.path.insert(0, _sdk_path)

# Ensure project root is importable (for scripts/)
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
