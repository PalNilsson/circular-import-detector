"""Module entry so `python -m circular_import_detector` works."""
from .circular_import_detector import main

if __name__ == "__main__":
    raise SystemExit(main())
