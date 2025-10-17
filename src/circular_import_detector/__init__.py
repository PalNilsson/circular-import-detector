"""Public API for circular_import_detector.

Exposes:
    - CircularImportDetector: Core class to scan a project and detect circular imports.
    - main: CLI entry point used by the console script.
"""
from .circular_import_detector import CircularImportDetector, main

__all__ = ["CircularImportDetector", "main"]
