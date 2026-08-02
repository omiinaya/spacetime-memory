#!/usr/bin/env python3
"""BEAM - Belief-based Evaluation for Artificial Memory."""
import os, json, sys, time, math, re, argparse, uuid as _uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk', 'python'))
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DATA_DIR = os.path.join(REPO_ROOT, 'data')
SCENARIOS_PATH = os.path.join(DATA_DIR, 'beam_scenarios.json')
EMB = os.environ.get('EMBEDDER_URL', 'http://localhost:9090')
print('Short write test OK')
