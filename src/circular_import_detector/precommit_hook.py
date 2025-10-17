from __future__ import annotations

"""Pre-commit hook entry point for circular import detection.

This hook builds a full project graph once and **fails only if** an SCC includes
an edge whose source file is among the staged files. That keeps it both fast and
actionable for developers.

Usage (in a consumer project's `.pre-commit-config.yaml`):

    - repo: local
      hooks:
        - id: circular-imports
          name: Check for circular imports (changed files)
          entry: circular-import-precommit
          language: python
          additional_dependencies: [circular-import-detector==<version>]
          pass_filenames: true
          types_or: [python]
"""

import argparse
from pathlib import Path
from typing import List, Set, Tuple

from .circular_import_detector import CircularImportDetector


def _changed_paths(repo_root: Path, filenames: List[str]) -> Set[Path]:
    """Normalize and resolve the staged filenames to absolute paths.

    Args:
        repo_root: Root directory of the repo being checked.
        filenames: Staged file paths as passed by pre-commit.

    Returns:
        A set of absolute Paths.
    """
    out: Set[Path] = set()
    for f in filenames:
        p = Path(f)
        p = (repo_root / p).resolve() if not p.is_absolute() else p.resolve()
        out.add(p)
    return out


def main(argv: List[str] | None = None) -> int:
    """Run the pre-commit hook.

    Reads staged filenames from pre-commit, builds a full graph once, then
    filters SCCs to those formed by edges originating in changed files.

    Args:
        argv: Optional list of CLI args provided by pre-commit.

    Returns:
        Exit code 1 if a relevant circular import is found; otherwise 0.
    """
    ap = argparse.ArgumentParser(description="Pre-commit hook for circular imports")
    ap.add_argument("filenames", nargs="*")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    det = CircularImportDetector(str(repo_root))
    has_cycles, groups = det.detect_circular_imports()

    # If pre-commit passed nothing (non-Python commit etc.), allow commit.
    if not args.filenames:
        return 0

    changed_paths = _changed_paths(repo_root, args.filenames)

    # Keep SCCs where any edge originates in a changed file.
    filtered: List[List[str]] = []
    for comp in groups:
        comp_set = set(comp)
        edges_in_group: Set[Tuple[str, str]] = {
            (u, v) for u in comp_set for v in det.module_graph.get(u, ()) if v in comp_set
        }
        keep = False
        for (u, v) in edges_in_group:
            for (fp, _lineno, _raw) in det.edge_meta.get((u, v), ()):
                if Path(fp).resolve() in changed_paths:
                    keep = True
                    break
            if keep:
                break
        if keep:
            filtered.append(comp)

    if filtered:
        print(det.format_cycles(filtered))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
