"""Pytest configuration and fixtures."""

import pytest
import sys
from pathlib import Path

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent / ".github" / "scripts"
sys.path.insert(0, str(scripts_dir))
