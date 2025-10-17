#!/usr/bin/env python3
"""
Example usage of the circular import detector.

This script demonstrates how to use the CircularImportDetector
programmatically in your own Python projects.
"""

from circular_import_detector import CircularImportDetector
import tempfile
from pathlib import Path


def create_example_project():
    """Create a temporary project with circular imports for demonstration."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp(prefix="circular_import_demo_")
    temp_path = Path(temp_dir)

    # Create some Python files with circular imports

    # Simple circular import: A -> B -> A
    (temp_path / "module_a.py").write_text("""
# Module A
import module_b

def function_a():
    return module_b.function_b()
""")

    (temp_path / "module_b.py").write_text("""
# Module B
import module_a

def function_b():
    # This creates a circular dependency
    return "B depends on A: " + str(module_a)
""")

    # Complex circular import: C -> D -> E -> C
    (temp_path / "module_c.py").write_text("""
# Module C
from module_d import process_data

def start_workflow():
    return process_data("start")
""")

    (temp_path / "module_d.py").write_text("""
# Module D
from module_e import validate

def process_data(data):
    if validate(data):
        return f"Processed: {data}"
    return "Invalid data"
""")

    (temp_path / "module_e.py").write_text("""
# Module E
from module_c import start_workflow  # This creates the cycle

def validate(data):
    if data == "recursive":
        # This would cause infinite recursion
        return start_workflow() is not None
    return len(data) > 0
""")

    # Non-circular module
    (temp_path / "utils.py").write_text("""
# Utility module with no circular dependencies
import os
import sys

def helper_function():
    return "This is safe!"
""")

    # Package with circular imports
    package_dir = temp_path / "mypackage"
    package_dir.mkdir()

    (package_dir / "__init__.py").write_text("""
# Package init
from .models import Model
""")

    (package_dir / "models.py").write_text("""
# Models module
from .views import render_model

class Model:
    def __str__(self):
        return render_model(self)
""")

    (package_dir / "views.py").write_text("""
# Views module
from .models import Model  # Creates cycle with models.py

def render_model(model):
    return f"<Model: {model.__class__.__name__}>"
""")

    return temp_dir


def demonstrate_basic_usage():
    """Demonstrate basic usage of the detector."""
    print("=== Circular Import Detector Demo ===\n")

    # Create example project
    print("1. Creating example project with circular imports...")
    project_dir = create_example_project()
    print(f"   Created temporary project at: {project_dir}\n")

    # Initialize detector
    print("2. Initializing detector...")
    detector = CircularImportDetector(project_dir)
    print("   ✓ Detector initialized\n")

    # Detect circular imports
    print("3. Analyzing project for circular imports...")
    has_cycles, cycles = detector.detect_circular_imports()
    print(f"   Analysis complete. Found cycles: {has_cycles}\n")

    # Display results
    print("4. Results:")
    if has_cycles:
        print(f"   ❌ Found {len(cycles)} circular import cycle(s)!\n")
        formatted_output = detector.format_cycles(cycles)
        print(formatted_output)
    else:
        print("   ✅ No circular imports detected!")

    # Cleanup
    print(f"\n5. Cleaning up temporary directory: {project_dir}")
    import shutil
    shutil.rmtree(project_dir)
    print("   ✓ Cleanup complete")


def demonstrate_programmatic_usage():
    """Show how to use the detector in your own code."""
    print("\n=== Programmatic Usage Example ===\n")

    project_dir = create_example_project()

    try:
        # Example: Custom analysis workflow
        detector = CircularImportDetector(project_dir)

        # Get list of Python files
        python_files = detector.find_python_files()
        print(f"Found {len(python_files)} Python files:")
        for file in python_files:
            relative_path = file.relative_to(detector.project_root)
            print(f"  - {relative_path}")

        print("\nBuilding module dependency graph...")

        # Analyze each file
        for file_path in python_files:
            detector.analyze_file(file_path)

        # Show the dependency graph
        print("\nModule dependencies:")
        for module, imports in detector.module_graph.items():
            if imports:  # Only show modules that import others
                print(f"  {module} imports: {', '.join(sorted(imports))}")

        # Find and report cycles
        cycles = detector.find_cycles()
        print("\nCycle detection results:")
        if cycles:
            for i, cycle in enumerate(cycles, 1):
                print(f"  Cycle {i}: {' -> '.join(cycle)}")
        else:
            print("  No cycles found")

    finally:
        import shutil
        shutil.rmtree(project_dir)


def demonstrate_integration_patterns():
    """Show common integration patterns."""
    print("\n=== Integration Patterns ===\n")

    # Pattern 1: CI/CD Integration
    print("Pattern 1: CI/CD Integration")
    print("In your CI/CD pipeline:")
    print("""
    # .github/workflows/check-imports.yml
    - name: Check for circular imports
      run: |
        pip install circular-import-detector
        circular-import-detector --exit-code .
    """)

    # Pattern 2: Pre-commit Hook
    print("\nPattern 2: Pre-commit Hook")
    print("In your .pre-commit-config.yaml:")
    print("""
    repos:
      - repo: local
        hooks:
          - id: circular-imports
            name: Check for circular imports
            entry: python precommit_hook.py
            language: system
            files: \\.py$
    """)

    # Pattern 3: Custom Validation
    print("\nPattern 3: Custom Validation Script")
    print("""
    def validate_project_imports(project_path):
        from circular_import_detector import CircularImportDetector

        detector = CircularImportDetector(project_path)
        has_cycles, cycles = detector.detect_circular_imports()

        if has_cycles:
            print("Circular imports detected!")
            for cycle in cycles:
                print(f"  Cycle: {' -> '.join(cycle)}")
            return False
        return True
    """)


if __name__ == "__main__":
    demonstrate_basic_usage()
    demonstrate_programmatic_usage()
    demonstrate_integration_patterns()

    print("\n=== Demo Complete ===")
    print("For more information, see README.md or run:")
    print("  python circular_import_detector.py --help")
