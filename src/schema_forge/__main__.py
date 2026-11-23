"""Module entry point: python -m schema_forge."""

from __future__ import annotations

import sys

from schema_forge.cli import main

if __name__ == "__main__":
    sys.exit(main())
