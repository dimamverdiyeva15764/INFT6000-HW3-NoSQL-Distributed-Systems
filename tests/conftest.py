import os
import sys

# Make "import app" / "import workload" work however pytest is started.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
