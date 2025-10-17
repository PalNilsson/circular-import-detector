#!/usr/bin/env python3
"""
Pre-commit hook wrapper for the circular import detector.

This script is designed to be called by pre-commit and will analyze only
the files that are being committed.
"""

import sys
import argparse
from pathlib import Path
from circular_import_detector import CircularImportDetector


def main():
    """Pre-commit hook entry point."""
    parser = argparse.ArgumentParser(
        description="Pre-commit hook for detecting circular imports"
    )
    parser.add_argument(
        "filenames",
        nargs="*",
        help="Files to check (provided by pre-commit)"
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Root directory of the Python project (default: current directory)"
    )

    args = parser.parse_args()

    # Filter to only Python files
    python_files = [f for f in args.filenames if f.endswith('.py')]

    if not python_files:
        # No Python files to check
        sys.exit(0)

    # Get the project root
    project_root = Path(args.project_root).resolve()

    # Run the circular import detector
    detector = CircularImportDetector(str(project_root))
    has_cycles, cycles = detector.detect_circular_imports()

    if has_cycles:
        print("❌ Circular imports detected!", file=sys.stderr)
        print(detector.format_cycles(cycles), file=sys.stderr)
        print("\nCommit blocked. Please fix the circular imports before committing.", file=sys.stderr)
        sys.exit(1)
    else:
        print("✅ No circular imports detected.")
        sys.exit(0)


if __name__ == "__main__":
    main()
