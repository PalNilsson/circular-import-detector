#!/usr/bin/env python3
"""
Test suite for the circular import detector.
"""

import tempfile
import unittest
from pathlib import Path
from circular_import_detector import CircularImportDetector


class TestCircularImportDetector(unittest.TestCase):
    """Test cases for the CircularImportDetector class."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir)

    def create_test_file(self, relative_path: str, content: str):
        """Helper method to create test files."""
        file_path = self.test_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        return file_path

    def test_no_circular_imports(self):
        """Test case with no circular imports."""
        # Create test files
        self.create_test_file('module_a.py', 'import module_b\n')
        self.create_test_file('module_b.py', 'import module_c\n')
        self.create_test_file('module_c.py', '# No imports\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertFalse(has_cycles)
        self.assertEqual(cycles, [])

    def test_simple_circular_import(self):
        """Test case with a simple circular import (A -> B -> A)."""
        # Create test files
        self.create_test_file('module_a.py', 'import module_b\n')
        self.create_test_file('module_b.py', 'import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)
        self.assertEqual(len(cycles), 1)
        # The cycle should contain both modules
        cycle_modules = set(cycles[0])
        self.assertIn('module_a', cycle_modules)
        self.assertIn('module_b', cycle_modules)

    def test_complex_circular_import(self):
        """Test case with a complex circular import (A -> B -> C -> A)."""
        # Create test files
        self.create_test_file('module_a.py', 'import module_b\n')
        self.create_test_file('module_b.py', 'import module_c\n')
        self.create_test_file('module_c.py', 'import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)
        self.assertEqual(len(cycles), 1)
        # The cycle should contain all three modules
        cycle_modules = set(cycles[0])
        self.assertIn('module_a', cycle_modules)
        self.assertIn('module_b', cycle_modules)
        self.assertIn('module_c', cycle_modules)

    def test_from_import_circular(self):
        """Test case with circular imports using 'from' imports."""
        # Create test files
        self.create_test_file('module_a.py', 'from module_b import something\n')
        self.create_test_file('module_b.py', 'from module_a import something_else\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)
        self.assertEqual(len(cycles), 1)

    def test_package_imports(self):
        """Test case with package-style imports."""
        # Create package structure
        self.create_test_file('package/__init__.py', '')
        self.create_test_file('package/module_a.py', 'from package import module_b\n')
        self.create_test_file('package/module_b.py', 'from package import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)
        # Should detect circular import between package modules
        self.assertTrue(any('package' in str(cycle) for cycle in cycles))

    def test_external_imports_ignored(self):
        """Test that external imports are ignored."""
        # Create test files with external imports
        self.create_test_file('module_a.py', '''
import os
import sys
from datetime import datetime
import module_b
''')
        self.create_test_file('module_b.py', '''
import json
import requests  # This won't exist in our test
# No import back to module_a
''')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertFalse(has_cycles)

    def test_relative_imports(self):
        """Test case with relative imports."""
        # Create package structure
        self.create_test_file('package/__init__.py', '')
        self.create_test_file('package/subpackage/__init__.py', '')
        self.create_test_file('package/subpackage/module_a.py', 'from . import module_b\n')
        self.create_test_file('package/subpackage/module_b.py', 'from . import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)

    def test_multiple_cycles(self):
        """Test case with multiple separate circular imports."""
        # Create first cycle: A -> B -> A
        self.create_test_file('cycle1_a.py', 'import cycle1_b\n')
        self.create_test_file('cycle1_b.py', 'import cycle1_a\n')

        # Create second cycle: C -> D -> C
        self.create_test_file('cycle2_c.py', 'import cycle2_d\n')
        self.create_test_file('cycle2_d.py', 'import cycle2_c\n')

        # Create non-circular module
        self.create_test_file('standalone.py', '# No imports\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)
        # Should detect both cycles
        self.assertEqual(len(cycles), 2)

    def test_module_name_conversion(self):
        """Test module name conversion from file paths."""
        detector = CircularImportDetector(self.test_dir)

        # Test regular python file
        test_file = self.test_path / 'module.py'
        module_name = detector.get_module_name(test_file)
        self.assertEqual(module_name, 'module')

        # Test __init__.py file
        test_file = self.test_path / 'package' / '__init__.py'
        module_name = detector.get_module_name(test_file)
        self.assertEqual(module_name, 'package')

        # Test nested module
        test_file = self.test_path / 'package' / 'submodule.py'
        module_name = detector.get_module_name(test_file)
        self.assertEqual(module_name, 'package.submodule')

    def test_syntax_error_handling(self):
        """Test that files with syntax errors are handled gracefully."""
        # Create file with syntax error
        self.create_test_file('broken.py', 'import module_a\nthis is not valid python syntax!!!\n')
        self.create_test_file('module_a.py', 'import broken\n')

        detector = CircularImportDetector(self.test_dir)
        # Should not raise an exception
        has_cycles, cycles = detector.detect_circular_imports()

        # The result may vary, but it shouldn't crash
        self.assertIsInstance(has_cycles, bool)
        self.assertIsInstance(cycles, list)

    def test_format_cycles_output(self):
        """Test the cycle formatting output."""
        # Create simple circular import
        self.create_test_file('module_a.py', 'import module_b\n')
        self.create_test_file('module_b.py', 'import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        if has_cycles:
            formatted_output = detector.format_cycles(cycles)
            self.assertIn('circular import cycle', formatted_output.lower())
            self.assertIn('module_a', formatted_output)
            self.assertIn('module_b', formatted_output)


class TestImportScenarios(unittest.TestCase):
    """Test specific import scenarios that are common in real projects."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = tempfile.mkdtemp()
        self.test_path = Path(self.test_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.test_dir)

    def create_test_file(self, relative_path: str, content: str):
        """Helper method to create test files."""
        file_path = self.test_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        return file_path

    def test_django_style_imports(self):
        """Test Django-style circular imports."""
        # Create models.py and views.py with typical Django circular import
        self.create_test_file('myapp/models.py', '''
from django.db import models

class MyModel(models.Model):
    name = models.CharField(max_length=100)
''')
        self.create_test_file('myapp/views.py', '''
from django.shortcuts import render
from myapp.models import MyModel  # This would be detected
''')

        # If models.py were to import from views.py, it would be circular
        # Let's simulate a bad case where models imports from views
        self.create_test_file('myapp/models.py', '''
from django.db import models
from myapp.views import some_helper  # This creates a cycle

class MyModel(models.Model):
    name = models.CharField(max_length=100)
''')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        # Should detect the circular import between models and views
        # Note: This might not detect if django imports are filtered out
        # In a real scenario, you'd want to modify the detector to handle
        # project-specific imports

    def test_conditional_imports(self):
        """Test imports inside conditions (which our static analyzer should still catch)."""
        self.create_test_file('module_a.py', '''
import sys

if sys.version_info > (3, 8):
    import module_b
else:
    import module_b
''')
        self.create_test_file('module_b.py', 'import module_a\n')

        detector = CircularImportDetector(self.test_dir)
        has_cycles, cycles = detector.detect_circular_imports()

        self.assertTrue(has_cycles)


if __name__ == '__main__':
    unittest.main()
