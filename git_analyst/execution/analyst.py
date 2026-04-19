"""
analyst.py - Core logic for the Git Repository Analyst MCP.

Seven tools:
    analyze_complexity   - composite complexity score per Python file
    find_hotspots        - files with highest commit churn in a time window
    summarize_commits    - commit breakdown by author, day, and type
    detect_coupling      - import graph, hubs, and circular dependencies
    find_dead_code       - functions and classes defined but never used
    scan_code_smells     - long functions, deep nesting, missing docstrings, magic numbers
    map_test_coverage    - source files with no corresponding test file
"""

import ast
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import git
import networkx as nx

# ---------------------------------------------------------------------------
# Repo cache -lazy, supports multiple repos per session
# ---------------------------------------------------------------------------

_repo_cache: dict[str, git.Repo] = {}


def _get_repo(repo_path: str) -> git.Repo:
    if repo_path not in _repo_cache:
        try:
            _repo_cache[repo_path] = git.Repo(repo_path, search_parent_directories=True)
        except git.InvalidGitRepositoryError:
            raise ValueError(json.dumps({
                "error": "invalid_repo",
                "detail": f"No .git directory found at or above {repo_path}",
                "partial_results": None,
            }))
        except Exception as e:
            raise ValueError(json.dumps({
                "error": "repo_open_failed",
                "detail": str(e),
                "partial_results": None,
            }))
    return _repo_cache[repo_path]


def _iter_py_files(repo_path: str, cap: int = None) -> list[Path]:
    root = Path(repo_path)
    files = [
        p for p in root.rglob("*.py")
        if ".git" not in p.parts and "__pycache__" not in p.parts
    ]
    if cap and len(files) > cap:
        return files[:cap], True
    return files, False


# ---------------------------------------------------------------------------
# Tool 1: analyze_complexity
# ---------------------------------------------------------------------------

def _complexity_score(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    lines = source.splitlines()
    loc = len([l for l in lines if l.strip() and not l.strip().startswith("#")])

    functions = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))

    # Average nesting depth via node depth tracking
    depths = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                              ast.If, ast.For, ast.While, ast.With, ast.Try)):
            depth = 0
            parent = getattr(node, "_parent", None)
            while parent:
                depth += 1
                parent = getattr(parent, "_parent", None)
            depths.append(depth)

    avg_depth = round(sum(depths) / len(depths), 1) if depths else 0
    score = loc + (functions * 3) + (classes * 5) + (avg_depth * 2)

    return {"loc": loc, "functions": functions, "classes": classes,
            "avg_nesting": avg_depth, "score": round(score, 1)}


def analyze_complexity(repo_path: str, top_n: int = 10) -> str:
    files, capped = _iter_py_files(repo_path)
    results = []
    skipped = []

    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            stats = _complexity_score(source)
            if stats:
                results.append({"file": str(f.relative_to(repo_path)), **stats})
        except Exception as e:
            skipped.append(str(f.name))

    results.sort(key=lambda x: x["score"], reverse=True)
    top = results[:top_n]

    lines = [f"TOP {len(top)} MOST COMPLEX FILES in {Path(repo_path).name}\n"]
    for i, r in enumerate(top, 1):
        lines.append(
            f"{i:>2}. {r['file']}\n"
            f"     Score: {r['score']}  |  LOC: {r['loc']}  |  "
            f"Functions: {r['functions']}  |  Classes: {r['classes']}  |  "
            f"Avg nesting: {r['avg_nesting']}"
        )

    if capped:
        lines.append(f"\n[Capped at 50 files -repo is large]")
    if skipped:
        lines.append(f"\n[Skipped {len(skipped)} files due to parse errors]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 2: find_hotspots
# ---------------------------------------------------------------------------

def find_hotspots(repo_path: str, days_back: int = 90, top_n: int = 10) -> str:
    repo = _get_repo(repo_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    churn: dict[str, int] = defaultdict(int)
    last_touched: dict[str, datetime] = {}

    try:
        for commit in repo.iter_commits():
            committed_dt = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
            if committed_dt < cutoff:
                break
            for f in commit.stats.files:
                churn[f] += 1
                if f not in last_touched or committed_dt > last_touched[f]:
                    last_touched[f] = committed_dt
    except Exception as e:
        return json.dumps({"error": "commit_traversal_failed", "detail": str(e), "partial_results": None})

    if not churn:
        return f"No commits found in the last {days_back} days in {Path(repo_path).name}."

    # Get complexity scores for hotspot ranking
    py_files, _ = _iter_py_files(repo_path)
    complexity: dict[str, float] = {}
    for f in py_files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            stats = _complexity_score(source)
            if stats:
                rel = str(f.relative_to(repo_path)).replace("\\", "/")
                complexity[rel] = stats["score"]
        except Exception:
            pass

    ranked = []
    for filepath, count in churn.items():
    	normalized = filepath.replace("\\", "/")
    	comp = complexity.get(normalized, 0)
    	risk = round(count * (1 + comp / 100), 1)
    	ranked.append({
            "file": filepath,
            "commits": count,
            "complexity_score": comp,
            "risk_score": risk,
            "last_changed": last_touched.get(filepath, cutoff).strftime("%Y-%m-%d"),
        })

    ranked.sort(key=lambda x: x["risk_score"], reverse=True)
    top = ranked[:top_n]

    lines = [f"TOP {len(top)} HOTSPOTS in {Path(repo_path).name} (last {days_back} days)\n",
             "Risk = churn × complexity -highest risk files are both changed often AND complex.\n"]
    for i, r in enumerate(top, 1):
        lines.append(
            f"{i:>2}. {r['file']}\n"
            f"     Risk: {r['risk_score']}  |  Commits: {r['commits']}  |  "
            f"Complexity: {r['complexity_score']}  |  Last changed: {r['last_changed']}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3: summarize_commits
# ---------------------------------------------------------------------------

COMMIT_PREFIXES = ["feat", "fix", "chore", "refactor", "docs", "test", "style", "perf", "ci", "build"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def summarize_commits(repo_path: str, days_back: int = 30) -> str:
    repo = _get_repo(repo_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    by_author: dict[str, int] = defaultdict(int)
    by_day: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    total = 0

    try:
        for commit in repo.iter_commits():
            committed_dt = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
            if committed_dt < cutoff:
                break
            total += 1
            by_author[commit.author.name] += 1
            by_day[DAYS[committed_dt.weekday()]] += 1

            msg = commit.message.strip().lower()
            matched = False
            for prefix in COMMIT_PREFIXES:
                if msg.startswith(prefix):
                    by_type[prefix] += 1
                    matched = True
                    break
            if not matched:
                by_type["other"] += 1
    except Exception as e:
        return json.dumps({"error": "commit_traversal_failed", "detail": str(e), "partial_results": None})

    if total == 0:
        return f"No commits found in the last {days_back} days in {Path(repo_path).name}."

    top_author = max(by_author, key=by_author.get)
    busiest_day = max(by_day, key=by_day.get)

    lines = [f"COMMIT SUMMARY -{Path(repo_path).name} (last {days_back} days)\n",
             f"Total commits:   {total}",
             f"Most active:     {top_author} ({by_author[top_author]} commits)",
             f"Busiest day:     {busiest_day} ({by_day[busiest_day]} commits)\n",
             "By type:"]
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        bar = "#" * min(count, 20)
        lines.append(f"  {t:<12} {count:>4}  {bar}")

    lines.append("\nBy author:")
    for author, count in sorted(by_author.items(), key=lambda x: -x[1])[:8]:
        lines.append(f"  {author:<30} {count:>4} commits")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4: detect_coupling
# ---------------------------------------------------------------------------

FILE_CAP = 50


def detect_coupling(repo_path: str, top_n: int = 10) -> str:
    files, capped = _iter_py_files(repo_path, cap=FILE_CAP)

    G = nx.DiGraph()
    skipped = []

    for f in files:
        module = str(f.relative_to(repo_path)).replace("\\", "/").replace("/", ".").removesuffix(".py")
        G.add_node(module)
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            skipped.append(f.name)
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    G.add_edge(module, alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                G.add_edge(module, node.module.split(".")[0])

    # Most imported (highest in-degree)
    in_degrees = sorted(G.in_degree(), key=lambda x: x[1], reverse=True)
    hubs = [(n, d) for n, d in in_degrees if d > 0][:top_n]

    # Circular imports
    cycles = list(nx.simple_cycles(G))
    cycles = [c for c in cycles if len(c) > 1][:5]

    lines = [f"IMPORT COUPLING -{Path(repo_path).name}\n"]

    lines.append(f"Most-imported modules (hubs):")
    if hubs:
        for module, degree in hubs:
            lines.append(f"  {module:<40} imported by {degree} module{'s' if degree != 1 else ''}")
    else:
        lines.append("  (none detected)")

    lines.append(f"\nCircular imports:")
    if cycles:
        for cycle in cycles:
            lines.append(f"  {'  ->  '.join(cycle + [cycle[0]])}")
    else:
        lines.append("  None detected -clean dependency graph.")

    if capped:
        lines.append(f"\n[Capped at {FILE_CAP} files -repo has more Python files]")
    if skipped:
        lines.append(f"[Skipped {len(skipped)} files: parse errors]")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5: find_dead_code
# ---------------------------------------------------------------------------

def find_dead_code(repo_path: str) -> str:
    """
    Find functions and classes defined in the repo but never called or imported
    anywhere else. Uses two-pass AST analysis: collect definitions, then collect
    all names referenced across the entire codebase.
    """
    files, _ = _iter_py_files(repo_path)

    # Pass 1: collect all definitions {name -> file}
    definitions: dict[str, str] = {}
    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue
        rel = str(f.relative_to(repo_path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):  # skip private/dunder
                    definitions[node.name] = rel

    # Pass 2: collect all names used across all files
    used: set[str] = set()
    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                used.add(node.attr)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    used.add(node.func.id)

    dead = {name: path for name, path in definitions.items() if name not in used}

    if not dead:
        return f"No dead code detected in {Path(repo_path).name}. All public functions and classes are referenced."

    # Group by file
    by_file: dict[str, list[str]] = defaultdict(list)
    for name, path in dead.items():
        by_file[path].append(name)

    lines = [f"DEAD CODE in {Path(repo_path).name} ({len(dead)} unreferenced definitions)\n",
             "These public functions/classes are never called or imported:\n"]
    for filepath, names in sorted(by_file.items()):
        lines.append(f"  {filepath}")
        for name in sorted(names):
            lines.append(f"    - {name}()")

    lines.append("\nNote: private names (prefixed _) are excluded. Verify before deleting.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6: scan_code_smells
# ---------------------------------------------------------------------------

MAGIC_NUMBER_PATTERN = re.compile(r"\b(?<!\w)(\d{2,})\b")
MAGIC_NUMBER_WHITELIST = {0, 1, 2, 100, 1000}


def _count_lines(node) -> int:
    try:
        return node.end_lineno - node.lineno + 1
    except AttributeError:
        return 0


def _max_depth(node, current=0) -> int:
    BLOCK_TYPES = (ast.If, ast.For, ast.While, ast.With, ast.Try,
                   ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    max_d = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, BLOCK_TYPES):
            max_d = max(max_d, _max_depth(child, current + 1))
        else:
            max_d = max(max_d, _max_depth(child, current))
    return max_d


def scan_code_smells(repo_path: str) -> str:
    files, _ = _iter_py_files(repo_path)
    smells: list[dict] = []

    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue

        rel = str(f.relative_to(repo_path))
        lines_list = source.splitlines()

        # File-level: missing module docstring
        if not (isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant)):
            smells.append({"file": rel, "type": "missing_docstring", "detail": "Module has no docstring"})

        for node in ast.walk(tree):
            # Long functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                length = _count_lines(node)
                if length > 50:
                    smells.append({"file": rel, "type": "long_function",
                                   "detail": f"{node.name}() is {length} lines (limit: 50)"})

            # Deep nesting
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                depth = _max_depth(node)
                if depth > 4:
                    smells.append({"file": rel, "type": "deep_nesting",
                                   "detail": f"{node.name}() has nesting depth {depth} (limit: 4)"})

        # Magic numbers (scan source lines directly)
        for i, line in enumerate(lines_list, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for match in MAGIC_NUMBER_PATTERN.finditer(line):
                num = int(match.group())
                if num not in MAGIC_NUMBER_WHITELIST:
                    smells.append({"file": rel, "type": "magic_number",
                                   "detail": f"Line {i}: hardcoded {num}"})
                    break  # one per line to avoid spam

    if not smells:
        return f"No code smells detected in {Path(repo_path).name}."

    # Group by type for summary
    by_type: dict[str, list] = defaultdict(list)
    for s in smells:
        by_type[s["type"]].append(s)

    lines = [f"CODE SMELLS in {Path(repo_path).name} ({len(smells)} issues)\n"]
    order = ["long_function", "deep_nesting", "missing_docstring", "magic_number"]
    labels = {"long_function": "Long functions (>50 lines)",
              "deep_nesting": "Deep nesting (>4 levels)",
              "missing_docstring": "Missing module docstrings",
              "magic_number": "Magic numbers"}

    for t in order:
        group = by_type.get(t, [])
        if not group:
            continue
        lines.append(f"{labels[t]} ({len(group)}):")
        for s in group[:10]:
            lines.append(f"  {s['file']}: {s['detail']}")
        if len(group) > 10:
            lines.append(f"  ... and {len(group) - 10} more")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7: map_test_coverage
# ---------------------------------------------------------------------------

def map_test_coverage(repo_path: str) -> str:
    """
    File-based test coverage map. No pytest required.
    Finds test_*.py files, maps them to source files by name convention,
    and lists source files with no corresponding test.
    """
    root = Path(repo_path)
    all_py = [p for p in root.rglob("*.py")
              if ".git" not in p.parts and "__pycache__" not in p.parts]

    test_files = [p for p in all_py if p.name.startswith("test_") or p.name.endswith("_test.py")]
    source_files = [p for p in all_py if p not in test_files]

    # Build map: strip test_ prefix and _test suffix to get candidate source name
    covered: set[str] = set()
    test_map: dict[str, str] = {}
    for t in test_files:
        stem = t.stem
        if stem.startswith("test_"):
            candidate = stem[5:]  # strip test_
        elif stem.endswith("_test"):
            candidate = stem[:-5]  # strip _test
        else:
            candidate = stem
        covered.add(candidate)
        test_map[candidate] = str(t.relative_to(root))

    untested = [f for f in source_files if f.stem not in covered]
    tested = [f for f in source_files if f.stem in covered]

    total = len(source_files)
    pct = round(len(tested) / total * 100) if total else 0

    lines = [f"TEST COVERAGE MAP -{Path(repo_path).name}\n",
             f"Coverage: {len(tested)}/{total} source files have a test file ({pct}%)\n"]

    if tested:
        lines.append("Covered:")
        for f in sorted(tested):
            candidate = f.stem
            lines.append(f"  {str(f.relative_to(root)):<45} <- {test_map.get(candidate, '?')}")

    lines.append("")
    if untested:
        lines.append(f"No test file found ({len(untested)}):")
        for f in sorted(untested):
            lines.append(f"  {str(f.relative_to(root))}")
    else:
        lines.append("All source files have a corresponding test file.")

    lines.append("\nNote: file-name convention only (test_foo.py -> foo.py). Does not check what is actually tested inside.")
    return "\n".join(lines)
