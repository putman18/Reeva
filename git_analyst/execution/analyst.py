"""
analyst.py - Core logic for the Git Repository Analyst MCP.

Four tools:
    analyze_complexity   - composite complexity score per Python file
    find_hotspots        - files with highest commit churn in a time window
    summarize_commits    - commit breakdown by author, day, and type
    detect_coupling      - import graph, hubs, and circular dependencies
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
