#!/usr/bin/env python3
"""Generate LARGE labeled eval dataset -- thin wrapper."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_eval_dataset import main as _main
if __name__ == "__main__":
    sys.argv[1:1] = ["--size", "large"]
    _main()
