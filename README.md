# Circular Import Detector

A Python tool to detect circular imports in your Python projects. This tool analyzes import statements statically and builds a dependency graph to identify circular import cycles that would only be discovered at runtime.

## Features

- 🔍 **Static Analysis**: Detects circular imports without running your code
- 🎯 **Pre-commit Integration**: Prevents circular imports from being committed
- 📊 **Detailed Reporting**: Shows exactly which files and modules are involved in cycles
- 🏗️ **Package Support**: Handles complex package structures and relative imports
- ⚡ **Fast**: Efficiently processes large codebases
- 🛡️ **Safe**: Only analyzes internal project imports, ignores external dependencies

## Installation

### From Source

```bash
git clone <repository-url>
cd circular-import-detector
pip install -e .
```

### Using pip (when published)

```bash
pip install circular-import-detector
```

## Usage

### Command Line Interface

#### Basic Usage

```bash
# Check current directory
circular-import-detector

# Check specific directory
circular-import-detector /path/to/your/project

# Quiet mode (only show output if circular imports found)
circular-import-detector --quiet

# Exit with error code if circular imports found (useful for CI/CD)
circular-import-detector --exit-code
```

#### Example Output

```
Found 1 circular import cycle(s):

Cycle 1:
  module_a -> module_b
  module_b -> module_c
  module_c -> module_a (circular)
  Files involved:
    module_a: /path/to/project/module_a.py
    module_b: /path/to/project/module_b.py
    module_c: /path/to/project/module_c.py
```

### Pre-commit Hook Integration

The tool is designed to work seamlessly with [pre-commit](https://pre-commit.com/) to prevent circular imports from being committed to your repository.

#### Setup

1. **Install pre-commit** (if you haven't already):
   ```bash
   pip install pre-commit
   ```

2. **Add to your `.pre-commit-config.yaml`**:
```yaml
-   repo: local
    hooks:
      - id: circular-imports
        name: Check for circular imports (changed files)
        entry: circular-import-precommit
        language: python
        additional_dependencies:
          - circular-import-detector==1.0.18
        pass_filenames: true
        types_or: [python]
        stages: [pre-commit]
```

3. **Install the hooks**:
   ```bash
   pre-commit install
   ```

Now, every time you commit Python files, the tool will check for circular imports and block the commit if any are found.

### Programmatic Usage

You can also use the detector in your Python code:

```python
from circular_import_detector import CircularImportDetector

# Initialize detector
detector = CircularImportDetector('/path/to/your/project')

# Detect circular imports
has_cycles, cycles = detector.detect_circular_imports()

if has_cycles:
    print(f"Found {len(cycles)} circular import cycles!")
    for cycle in cycles:
        print("Cycle:", " -> ".join(cycle))
else:
    print("No circular imports detected.")
```

## How It Works

The tool performs static analysis of your Python code by:

1. **Parsing Python files** using the `ast` module to extract import statements
2. **Building a dependency graph** of modules and their imports
3. **Filtering internal imports** to focus only on your project's modules
4. **Detecting cycles** using depth-first search algorithm
5. **Reporting results** with detailed information about each cycle

### Supported Import Types

- `import module`
- `from module import something`
- `from package.submodule import something`
- `from . import module` (relative imports)
- `from ..parent import module` (relative imports)

### What Gets Analyzed

- ✅ All `.py` files in your project
- ✅ Package structures with `__init__.py`
- ✅ Nested packages and submodules
- ✅ Relative imports within packages
- ❌ External dependencies (ignored)
- ❌ Dynamic imports (not detectable statically)

## Configuration

The tool works out of the box with sensible defaults, but you can customize its behavior:

### Project Structure

The detector automatically:
- Skips common non-source directories (`.git`, `__pycache__`, `build`, `dist`, etc.)
- Handles package structures correctly
- Converts file paths to proper module names

## Common Circular Import Patterns

### Simple Cycle
```python
# file_a.py
import file_b

# file_b.py
import file_a  # Creates cycle: file_a -> file_b -> file_a
```

### Complex Cycle
```python
# models.py
from views import get_context

# views.py
from utils import helper

# utils.py
from models import MyModel  # Creates cycle: models -> views -> utils -> models
```

### Package Cycle
```python
# package_a/__init__.py
from package_b import something

# package_b/__init__.py
from package_a import something_else  # Creates cycle
```

## Troubleshooting

### Common Issues

1. **"No Python files found"**
   - Ensure you're running the tool from the correct directory
   - Check that your Python files have `.py` extension

2. **Relative imports not detected correctly**
   - Ensure your package structure has proper `__init__.py` files
   - The tool analyzes from the project root you specify

3. **External imports being flagged**
   - This shouldn't happen, but if it does, the filtering logic may need adjustment
   - Open an issue with details about your project structure

### Performance Tips

- The tool is designed to handle large codebases efficiently
- For very large projects, consider running it on specific subdirectories
- Use `--quiet` mode in automated environments to reduce output

## Development

### Running Tests

```bash
python -m pytest test_circular_imports.py -v
```

### Running the Tool on Itself

```bash
# Test the tool on its own codebase
python circular_import_detector.py .
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for your changes
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License - see LICENSE file for details.
