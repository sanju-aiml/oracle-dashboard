import os
import sys

# Flag serverless mode
os.environ.setdefault("VERCEL", "1")

# Ensure project root is on the Python path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from server import app
