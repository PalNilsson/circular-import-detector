from __future__ import annotations

import argparse
import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict


# --------- AST collection -----------------------------------------------------

@dataclass(frozen=True)
class ImportRecord:
    raw: str        # raw dotted target as written (may be relative like "..sub.mod")
    lineno: int     # 1-based line number
    kind: str       # "import" | "from"


class ImportAnalyzer(ast.NodeVisitor):
    """Collect full import targets and line numbers."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            raw = alias.name  # keep full dotted module
            self.records.append(ImportRecord(raw=raw, lineno=node.lineno, kind="import"))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # build a base like "..pkg.sub" (relative dots + module)
        base = ('.' * (node.level or 0)) + (node.module or '')
        if node.names and any(a.name == "*" for a in node.names):
            raw = base or "."
            self.records.append(ImportRecord(raw=raw, lineno=node.lineno, kind="from"))
        else:
            sep = '.' if node.module else ''
            for a in node.names:
                raw = f"{base}{sep}{a.name}"
                self.records.append(ImportRecord(raw=raw, lineno=node.lineno, kind="from"))
        self.generic_visit(node)


# --------- Core detector ------------------------------------------------------

class CircularImportDetector:
    def __init__(self, project_path: str | os.PathLike[str]) -> None:
        self.project_root = Path(project_path).resolve()

        # Prefer src/ layout when present
        self.scan_root: Path = (self.project_root / "src") if (self.project_root / "src").is_dir() else self.project_root

        # Graphs & indices
        self.module_graph: Dict[str, Set[str]] = defaultdict(set)  # module -> set(imported modules)
        self.module_to_file: Dict[str, str] = {}                  # module -> file path
        self.file_to_module: Dict[str, str] = {}                  # file path -> module

        # Raw import collection with locations
        self._raw_import_locs: Dict[str, List[Tuple[str, int, str, str]]] = {}
        # maps src_module -> list of (raw, lineno, kind, file_path)

        # Edge metadata for pretty printing
        self.edge_meta: Dict[Tuple[str, str], List[Tuple[str, int, str]]] = defaultdict(list)
        # maps (src_module, dst_module) -> list of (file_path, lineno, raw)

    # ----- File system helpers -----

    def find_python_files(self) -> List[Path]:
        """Walk the repo and return .py files under scan_root (skip common junk)."""
        skip_dirs = {
            ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
            ".tox", "build", "dist", "node_modules", ".venv", "venv", ".eggs",
            ".ruff_cache", ".ruff_cache", ".idea", ".vscode"
        }
        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.scan_root):
            # prune
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
            for fn in filenames:
                if fn.endswith(".py"):
                    files.append(Path(root) / fn)
        return files

    def _path_to_module(self, file_path: Path) -> str:
        """
        Convert a python file path to a dotted module name, supporting src/ layout
        and namespace packages (PEP 420 – no __init__.py).
        """
        rel = file_path.resolve().relative_to(self.scan_root)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]  # strip .py
        # Drop empty segments and join with dots
        parts = [p for p in parts if p and p not in (".",)]
        return ".".join(parts)

    # ----- Parsing / indexing -----

    def analyze_file(self, file_path: Path) -> None:
        """Parse a file, record its module name and import records."""
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            return
        try:
            tree = ast.parse(text, filename=str(file_path))
        except SyntaxError:
            return

        analyzer = ImportAnalyzer()
        analyzer.visit(tree)

        module_name = self._path_to_module(file_path)
        abs_path = str(file_path.resolve())

        # Index
        self.module_to_file[module_name] = abs_path
        self.file_to_module[abs_path] = module_name

        # Store raw import locations: (raw, lineno, kind, file)
        self._raw_import_locs[module_name] = [(r.raw, r.lineno, r.kind, abs_path) for r in analyzer.records]

    # ----- Import resolution -----

    def _resolve_import_to_module(self, raw: str, src_module: Optional[str] = None) -> Optional[str]:
        """
        Resolve a raw import string (absolute or relative) to a module we actually
        scanned (present in self.module_to_file). Handles 'from .x import y' properly
        from both packages (__init__.py) and submodules.
        """
        if not raw:
            return None

        # Count leading dots for relative imports
        i = 0
        while i < len(raw) and raw[i] == '.':
            i += 1
        rel = i
        tail = raw[rel:]  # may include module segments and/or symbol name

        if rel == 0:
            # Absolute import: try longest-prefix match
            parts = [p for p in tail.split('.') if p]
            for j in range(len(parts), 0, -1):
                cand = '.'.join(parts[:j])
                if cand in self.module_to_file:
                    return cand
            return None

        # Relative import — need src_module context
        if not src_module:
            return None

        # Determine the *current package* of the source module
        # - if src is a package (__init__.py), package == src_module
        # - else package == parent of src_module
        src_file = self.module_to_file.get(src_module, "")
        is_pkg = src_file.endswith(os.sep + "__init__.py")
        if is_pkg:
            pkg_parts = src_module.split('.')
        else:
            pkg_parts = src_module.split('.')[:-1]  # parent package (may be [])

        # In Python, a single leading dot means "current package" (no upward move).
        # So we go up (rel - 1) packages.
        up = max(rel - 1, 0)
        if up >= len(pkg_parts):
            base_parts = []
        else:
            base_parts = pkg_parts[:-up] if up else pkg_parts

        tail_parts = [p for p in tail.split('.') if p]
        candidate_parts = base_parts + tail_parts

        # Longest-prefix match against modules we actually scanned
        for j in range(len(candidate_parts), 0, -1):
            cand = '.'.join(candidate_parts[:j])
            if cand in self.module_to_file:
                return cand
        return None

    # ----- SCC (Tarjan) -----

    def _tarjan_scc(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        index = 0
        stack: List[str] = []
        onstack: Set[str] = set()
        indices: Dict[str, int] = {}
        low: Dict[str, int] = {}
        sccs: List[List[str]] = []

        def strongconnect(v: str) -> None:
            nonlocal index
            indices[v] = index
            low[v] = index
            index += 1
            stack.append(v)
            onstack.add(v)

            for w in graph.get(v, ()):
                if w not in indices:
                    strongconnect(w)
                    low[v] = min(low[v], low[w])
                elif w in onstack:
                    low[v] = min(low[v], indices[w])

            if low[v] == indices[v]:
                comp: List[str] = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)

        for v in list(graph.keys()):
            if v not in indices:
                strongconnect(v)
        return sccs

    # ----- Public detection API -----

    def detect_circular_imports(self) -> Tuple[bool, List[List[str]]]:
        """
        Scan, build dependency graph (module level), and find all circular groups.
        Returns (has_cycles, groups). Each group is a list of modules forming an SCC.
        """
        # Reset state
        self.module_graph.clear()
        self._raw_import_locs.clear()
        self.edge_meta.clear()

        # 1) Scan all Python files and collect raw imports + locations
        for file_path in self.find_python_files():
            self.analyze_file(file_path)

        # 2) Build directed graph + edge metadata
        for src_module, recs in self._raw_import_locs.items():
            for raw, lineno, _kind, file_path in recs:
                tgt = self._resolve_import_to_module(raw, src_module)
                if not tgt or tgt == src_module:  # <-- skip self-edges
                    continue
                self.module_graph[src_module].add(tgt)
                self.edge_meta[(src_module, tgt)].append((file_path, lineno, raw))

        # Ensure all targets appear as nodes
        for v, nbrs in list(self.module_graph.items()):
            for w in nbrs:
                self.module_graph.setdefault(w, set())

        # 3) SCC
        sccs = self._tarjan_scc(self.module_graph)

        # 4) Keep only cycles (SCC size>1) or self-loops
        groups: List[List[str]] = []
        for comp in sccs:
            if len(comp) > 1:
                groups.append(sorted(comp))
            elif comp:
                m = comp[0]
                if m in self.module_graph.get(m, set()):
                    groups.append([m])

        return (bool(groups), groups)

    # ----- Formatting -----

    def format_cycles(self, cycles: List[List[str]], show_snippet: bool = False) -> str:
        if not cycles:
            return "No circular imports detected."

        out = [f"Found {len(cycles)} circular import group(s):", ""]
        for i, cycle in enumerate(cycles, 1):
            out.append(f"Group {i}:")
            ring = " -> ".join(cycle + [cycle[0]])
            out.append(f"  {ring}")

            # Explain the exact edges with file+line
            out.append("  Explicit imports causing this cycle:")
            for a, b in zip(cycle, cycle[1:] + [cycle[0]]):
                sites = self.edge_meta.get((a, b), [])
                if not sites:
                    out.append(f"    {a} → {b}: (location unknown)")
                    continue
                for j, (fp, lineno, raw) in enumerate(sites[:3], 1):
                    loc = f"{fp}:{lineno}" if lineno else fp
                    out.append(f"    {a} → {b}: {loc}   import '{raw}'")
                    if show_snippet and lineno:
                        try:
                            line = Path(fp).read_text(encoding="utf-8").splitlines()[lineno - 1].rstrip()
                            out.append(f"      > {line}")
                        except Exception:
                            pass
                if len(sites) > 3:
                    out.append(f"    … {len(sites)-3} more location(s)")

            # Files involved (summary)
            out.append("  Files involved:")
            for mod in cycle:
                p = self.module_to_file.get(mod)
                if p:
                    out.append(f"    {mod}: {p}")
            out.append("")
        return "\n".join(out).rstrip()


# --------- CLI ---------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect circular imports in Python projects",
        prog="circular-import-detector",
    )
    parser.add_argument("project_path", nargs="?", default=".", help="Path to the Python project directory (default: current directory)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only output if circular imports are found")
    parser.add_argument("--exit-code", action="store_true", help="Exit with code 1 if circular imports are found (useful for CI/CD)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show import source lines for each edge")

    args = parser.parse_args(argv)

    detector = CircularImportDetector(args.project_path)
    has_cycles, cycles = detector.detect_circular_imports()

    if has_cycles:
        print(detector.format_cycles(cycles, show_snippet=args.verbose))
    elif not args.quiet:
        print("No circular imports detected.")

    if args.exit_code and has_cycles:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
