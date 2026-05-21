"""Shared test fixtures and setup for the ai-tuning-workbench test suite.

Filters out ROS2 packages from sys.path that can cause pytest plugin conflicts.
"""

import sys
from pathlib import Path

# Remove ROS-related paths that pollute pytest with incompatible plugins
_bad_prefixes = ["/opt/ros/"]
sys.path = [p for p in sys.path if not any(p.startswith(bp) for bp in _bad_prefixes)]

# Ensure matplotlib uses non-interactive backend for all tests
import matplotlib
matplotlib.use("Agg")
