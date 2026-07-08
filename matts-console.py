#!/usr/bin/env python3
"""Run the Matts Value Set unified web console."""
import runpy
from pathlib import Path


runpy.run_path(str(Path(__file__).resolve().with_name("image-studio.py")), run_name="__main__")
