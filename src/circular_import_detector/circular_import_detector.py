from __future__ import annotations

import argparse
import ast
import os
# import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
from collections import defaultdict


# =============================================================================
# AST collection
# =============================================================================

@dataclass(frozen=True)
class ImportRecord:
    """One import occurrence as found by the AST visitor.

    Attributes:
        raw: Raw dotted import target as it appears in code (can be relative: "..sub.mod").
        lineno: 1-based line number of the import statement.
        kind: "import" or "from".
    """
    raw: str
    lineno: int
    kind: str


class ImportAnalyzer(ast.NodeVisitor):
    """Collect full import targets and line numbers from a Python source AST."""

    def __init__(self) -> None:
        super().__init__()
        self.records: List[ImportRecord] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            # Keep the full dotted module (no truncation here).
            self.records.append(
                ImportRecord(raw=alias.name, lineno=node.lineno, kind="import")
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Build a base like "..pkg.sub" (relative dots + module).
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


# =============================================================================
# Core detector
# =============================================================================

class CircularImportDetector:
    """Detect circular imports in a Python project.

    This class scans the project directory (preferring a ``src/`` layout if present),
    builds a module-level import graph, finds strongly connected components (SCCs),
    and reports them as circular import groups.

    Args:
        project_path: Path to the project root directory. If a ``src/`` directory
            exists within it, scanning will start from there; otherwise from
            ``project_path`` itself.
    """

    def __init__(self, project_path: str | os.PathLike[str]) -> None:
        self.project_root = Path(project_path).resolve()
        self.scan_root: Path = (
            self.project_root / "src"
            if (self.project_root / "src").is_dir()
            else self.project_root
        )

        # Graphs & indices
        self.module_graph: Dict[str, Set[str]] = defaultdict(set)  # module -> imports
        self.module_to_file: Dict[str, str] = {}                  # module -> file path
        self.file_to_module: Dict[str, str] = {}                  # file path -> module

        # Raw import collection with locations:
        # src_module -> list[(raw, lineno, kind, file_path)]
        self._raw_import_locs: Dict[str, List[Tuple[str, int, str, str]]] = {}

        # Edge metadata for formatting:
        # (src_module, dst_module) -> list[(file_path, lineno, raw)]
        self.edge_meta: Dict[Tuple[str, str], List[Tuple[str, int, str]]] = defaultdict(list)

    # -------------------------------------------------------------------------
    # File system helpers
    # -------------------------------------------------------------------------

    def find_python_files(self) -> List[Path]:
        """Return all Python files under the scan root, skipping common junk.

        Returns:
            List of paths to ``.py`` files.
        """
        skip_dirs = {
            ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
            ".tox", "build", "dist", "node_modules", ".venv", "venv", ".eggs",
            ".ruff_cache", ".idea", ".vscode"
        }
        files: List[Path] = []
        for root, dirs, filenames in os.walk(self.scan_root):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
            for fn in filenames:
                if fn.endswith(".py"):
                    files.append(Path(root) / fn)
        return files

    def _path_to_module(self, file_path: Path) -> str:
        """Convert a file path to a dotted module name.

        Supports both flat and ``src/`` layouts. Treats folders as namespace
        packages even without ``__init__.py``.

        Args:
            file_path: Path to a Python source file.

        Returns:
            Dotted module path relative to ``scan_root``.
        """
        rel = file_path.resolve().relative_to(self.scan_root)
        parts = list(rel.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = parts[-1][:-3]  # strip .py
        parts = [p for p in parts if p and p != "."]
        return ".".join(parts)

    # -------------------------------------------------------------------------
    # Parsing / indexing
    # -------------------------------------------------------------------------

    def analyze_file(self, file_path: Path) -> None:
        """Parse a file, record its module name and import records.

        Args:
            file_path: Path to the file to analyze.
        """
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

        self.module_to_file[module_name] = abs_path
        self.file_to_module[abs_path] = module_name
        self._raw_import_locs[module_name] = [
            (rec.raw, rec.lineno, rec.kind, abs_path) for rec in analyzer.records
        ]

    # -------------------------------------------------------------------------
    # Import resolution
    # -------------------------------------------------------------------------

    def _resolve_import_to_module(self, raw: str, src_module: Optional[str] = None) -> Optional[str]:
        """Resolve a raw import to a module present in ``module_to_file``.

        Handles absolute and relative forms (e.g., ``from .x import y``). For
        relatives, the resolution is performed relative to the **package** of
        ``src_module`` (i.e., the module's parent unless it is itself a package
        ``__init__.py``), and supports "stay in current package" semantics for a
        single leading dot.

        Args:
            raw: Raw dotted import string as collected (may be relative).
            src_module: Source module performing the import; required for relatives.

        Returns:
            The best-matching (longest-prefix) module name found in
            ``module_to_file``, or ``None`` if the import cannot be resolved.
        """
        if not raw:
            return None

        # Count leading dots (relative level)
        i = 0
        while i < len(raw) and raw[i] == '.':
            i += 1
        rel = i
        tail = raw[rel:]

        if rel == 0:
            # Absolute import: try longest-prefix match directly.
            parts = [p for p in tail.split('.') if p]
            for j in range(len(parts), 0, -1):
                cand = '.'.join(parts[:j])
                if cand in self.module_to_file:
                    return cand
            return None

        # Relative import – need source module context.
        if not src_module:
            return None

        src_file = self.module_to_file.get(src_module, "")
        is_pkg = src_file.endswith(os.sep + "__init__.py")
        if is_pkg:
            pkg_parts = src_module.split('.')
        else:
            pkg_parts = src_module.split('.')[:-1]  # parent package

        # One leading dot means "current package" (no upward move).
        up = max(rel - 1, 0)
        base_parts = pkg_parts[:-up] if up else pkg_parts

        tail_parts = [p for p in tail.split('.') if p]
        candidate_parts = base_parts + tail_parts

        for j in range(len(candidate_parts), 0, -1):
            cand = '.'.join(candidate_parts[:j])
            if cand in self.module_to_file:
                return cand
        return None

    # -------------------------------------------------------------------------
    # Tarjan SCC
    # -------------------------------------------------------------------------

    def _tarjan_scc(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        """Compute strongly connected components using Tarjan's algorithm.

        Args:
            graph: Directed adjacency list mapping module -> set(imported modules).

        Returns:
            List of components; each is a list of modules.
        """
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

    # -------------------------------------------------------------------------
    # Public detection API
    # -------------------------------------------------------------------------

    def detect_circular_imports(self) -> Tuple[bool, List[List[str]]]:
        """Scan the project and return all circular import groups.

        Returns:
            Tuple ``(has_cycles, groups)`` where:
                - ``has_cycles`` is ``True`` if any circular group is found.
                - ``groups`` is a list of SCCs (each SCC is a list of modules).
        """
        # Reset state
        self.module_graph.clear()
        self._raw_import_locs.clear()
        self.edge_meta.clear()

        # 1) Scan and collect raw imports
        for file_path in self.find_python_files():
            self.analyze_file(file_path)

        # 2) Build graph + edge metadata
        for src_module, recs in self._raw_import_locs.items():
            for raw, lineno, _kind, file_path in recs:
                tgt = self._resolve_import_to_module(raw, src_module)
                if not tgt or tgt == src_module:  # skip self-edges
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

        return bool(groups), groups

    # -------------------------------------------------------------------------
    # Formatting (split helpers to reduce complexity)
    # -------------------------------------------------------------------------

    def _edges_in_component(self, comp: List[str]) -> List[Tuple[str, str]]:
        """Return the set of edges whose endpoints are both inside ``comp``."""
        comp_set = set(comp)
        return sorted(
            {(u, v) for u in comp_set for v in self.module_graph.get(u, ()) if v in comp_set}
        )

    def _find_one_cycle_in_component(self, comp: List[str]) -> List[str]:
        """Find a representative simple cycle path within an SCC via DFS.

        Args:
            comp: Modules in the SCC.

        Returns:
            A list of modules representing one cycle path ending back at the start,
            or an empty list if not found (should not happen for a valid SCC).
        """
        comp_set = set(comp)
        graph = {u: [v for v in self.module_graph.get(u, ()) if v in comp_set] for u in comp_set}
        for start in comp:
            stack: List[Tuple[str, List[str], Set[str]]] = [(start, [start], {start})]
            while stack:
                node, path, seen = stack.pop()
                for nxt in graph.get(node, ()):
                    if nxt == start and len(path) > 1:
                        return path + [start]
                    if nxt not in seen:
                        stack.append((nxt, path + [nxt], seen | {nxt}))
        return []

    def _format_component_report(
        self, comp: List[str], index: int, show_snippet: bool
    ) -> List[str]:
        """Format a single SCC (component) into human-readable lines."""
        out: List[str] = [f"Group {index}:"]
        rep = self._find_one_cycle_in_component(comp)
        if rep:
            out.append("  Representative cycle:")
            out.append("    " + " -> ".join(rep))
        else:
            out.append("  Modules in group:")
            out.append("    " + ", ".join(sorted(comp)))

        out.append("  Imports forming this group:")
        for (u, v) in self._edges_in_component(comp):
            sites = self.edge_meta.get((u, v), [])
            if not sites:
                out.append(f"    {u} → {v}: (location unknown)")
                continue
            for (fp, lineno, raw) in sites[:3]:
                loc = f"{fp}:{lineno}" if lineno else fp
                out.append(f"    {u} → {v}: {loc}   import '{raw}'")
                if show_snippet and lineno:
                    try:
                        line = Path(fp).read_text(encoding="utf-8").splitlines()[lineno - 1].rstrip()
                        out.append(f"      > {line}")
                    except Exception:
                        # Best-effort: ignore snippet errors (permissions, etc.)
                        pass
            if len(sites) > 3:
                out.append(f"    … {len(sites) - 3} more location(s)")

        out.append("  Files involved:")
        for mod in sorted(comp):
            p = self.module_to_file.get(mod)
            if p:
                out.append(f"    {mod}: {p}")
        out.append("")  # trailing blank line between groups
        return out

    def format_cycles(self, cycles: List[List[str]], show_snippet: bool = False) -> str:
        """Return a human-readable report for all cycles.

        Args:
            cycles: List of SCCs (each SCC is a list of modules).
            show_snippet: If True, include the source line for each import.

        Returns:
            A formatted string suitable for printing to the console.
        """
        if not cycles:
            return "No circular imports detected."

        out: List[str] = [f"Found {len(cycles)} circular import group(s):", ""]
        for i, comp in enumerate(cycles, 1):
            out.extend(self._format_component_report(comp, i, show_snippet))
        return "\n".join(out).rstrip()


# =============================================================================
# CLI
# =============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    """Command-line interface for circular import detection.

    Args:
        argv: Optional list of CLI arguments. If ``None``, ``sys.argv[1:]`` is used.

    Returns:
        Process exit code: ``0`` for no cycles (or quiet mode), ``1`` when
        ``--exit-code`` is specified and cycles were found.
    """
    parser = argparse.ArgumentParser(
        description="Detect circular imports in Python projects",
        prog="circular-import-detector",
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        default=".",
        help="Path to the Python project directory (default: current directory)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output if circular imports are found",
    )
    parser.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with code 1 if circular imports are found (useful for CI/CD)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show import source lines for each edge",
    )

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
