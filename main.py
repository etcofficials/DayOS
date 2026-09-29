"""DayOS entry point.

    .venv\\Scripts\\python.exe main.py            # launch
    .venv\\Scripts\\python.exe main.py --smoke-test
"""

import sys

from src.app import run

if __name__ == "__main__":
    sys.exit(run())
