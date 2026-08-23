"""AI Trading Council — Entrypoint for Streamlit & Local."""
import os
import runpy
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

dashboard_path = os.path.join(BASE, "dashboard.py")
runpy.run_path(dashboard_path, run_name="__main__")
