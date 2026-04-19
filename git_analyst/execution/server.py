"""
server.py - FastMCP stdio server for the Git Repository Analyst MCP.

Tools:
  analyze_complexity   - top N most complex Python files by composite score
  find_hotspots        - files with highest churn x complexity risk
  summarize_commits    - commit breakdown by author, day, type
  detect_coupling      - import hubs and circular dependencies
  find_dead_code       - public functions/classes never called or imported
  scan_code_smells     - long functions, deep nesting, magic numbers, missing docstrings
  map_test_coverage    - source files with no corresponding test file

Usage:
  python git_analyst/execution/server.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP
from git_analyst.execution.analyst import (
    analyze_complexity,
    find_hotspots,
    summarize_commits,
    detect_coupling,
    find_dead_code,
    scan_code_smells,
    map_test_coverage,
)

mcp = FastMCP("git-analyst")


@mcp.tool()
def analyze_complexity_tool(repo_path: str, top_n: int = 10) -> str:
    """
    Rank Python files in a repo by complexity: lines of code, function count,
    class count, and average nesting depth combined into a composite score.
    repo_path: absolute path to the repo root (e.g. C:/Users/you/myproject).
    """
    return analyze_complexity(repo_path, top_n=top_n)


@mcp.tool()
def find_hotspots_tool(repo_path: str, days_back: int = 90, top_n: int = 10) -> str:
    """
    Find the highest-risk files: those that are both complex AND frequently changed.
    Risk score = commit count × complexity. Covers the last N days of history.
    repo_path: absolute path to the repo root.
    """
    return find_hotspots(repo_path, days_back=days_back, top_n=top_n)


@mcp.tool()
def summarize_commits_tool(repo_path: str, days_back: int = 30) -> str:
    """
    Summarize commit activity: total commits, most active author, busiest day of week,
    and breakdown by conventional commit type (feat, fix, chore, refactor, etc.).
    repo_path: absolute path to the repo root.
    """
    return summarize_commits(repo_path, days_back=days_back)


@mcp.tool()
def detect_coupling_tool(repo_path: str, top_n: int = 10) -> str:
    """
    Build an import graph across all Python files. Returns the most-imported modules
    (dependency hubs) and any circular import chains. Capped at 50 files for performance.
    repo_path: absolute path to the repo root.
    """
    return detect_coupling(repo_path, top_n=top_n)


@mcp.tool()
def find_dead_code_tool(repo_path: str) -> str:
    """
    Find public functions and classes defined in the repo but never called or imported anywhere.
    Two-pass AST analysis: collect all definitions, then collect all referenced names.
    repo_path: absolute path to the repo root.
    """
    return find_dead_code(repo_path)


@mcp.tool()
def scan_code_smells_tool(repo_path: str) -> str:
    """
    Scan for common code quality issues: functions over 50 lines, nesting depth over 4,
    missing module docstrings, and magic numbers hardcoded in logic.
    repo_path: absolute path to the repo root.
    """
    return scan_code_smells(repo_path)


@mcp.tool()
def map_test_coverage_tool(repo_path: str) -> str:
    """
    File-based test coverage map. No pytest required. Finds every test_*.py file,
    maps it to its source file by naming convention, and lists untested source files.
    repo_path: absolute path to the repo root.
    """
    return map_test_coverage(repo_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
