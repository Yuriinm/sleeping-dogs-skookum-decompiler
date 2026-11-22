#!/usr/bin/env python3
"""Convenience launcher: python sdskoo.py <game folder> <output folder>"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sdskoo.cli import main  # noqa: E402

sys.exit(main())
