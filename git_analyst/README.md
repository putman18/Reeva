# git-analyst MCP

A Model Context Protocol server that gives Claude 7 static analysis tools for any local Git repository. Point it at a codebase and ask plain-English questions — Claude calls the tools and reasons over the results.

Zero paid APIs. Pure Python. Runs locally via stdio.

---

## What it does

When you inherit or revisit a codebase, understanding it takes days. git-analyst answers the questions that matter in seconds:

| Tool | Question it answers |
|---|---|
| `analyze_complexity` | Which files are hardest to understand? |
| `find_hotspots` | Which files are complex AND constantly changing (highest risk)? |
| `summarize_commits` | What has this team been working on, and how? |
| `detect_coupling` | What does everything depend on? Any circular imports? |
| `find_dead_code` | Which functions and classes are defined but never used? |
| `scan_code_smells` | Where are the long functions, deep nesting, and magic numbers? |
| `map_test_coverage` | Which source files have no test file? |

---

## When to use this

**You just joined a new codebase.** You have no idea which files matter, who owns what, or where the skeletons are. Run `analyze_complexity` + `find_hotspots` first — they tell you where to spend your reading time and what to be careful touching.

**You're about to do a refactor.** `scan_code_smells` gives you a prioritized list of what to fix. `detect_coupling` tells you what will break if you move things. `find_dead_code` tells you what you can safely delete first.

**You're doing a code review on an unfamiliar PR.** `summarize_commits` tells you the team's recent rhythm. `map_test_coverage` tells you instantly whether there are tests for the files being changed.

**You're handing a codebase off to someone else.** Run all 7 tools and share the output as a "here's the state of the repo" document. It takes 30 seconds and tells the next person everything they need to know.

**You should NOT use this for:**
- Runtime performance profiling (it's static analysis only — it can't see what actually runs)
- Security scanning (use Bandit or Semgrep for that)
- Non-Python codebases (v1 is Python only)

---

## Example output

```
TOP 5 MOST COMPLEX FILES in voicebot

 1. execution/voicebot_agent.py
     Score: 417.0  |  LOC: 391  |  Functions: 7  |  Classes: 1
 2. execution/voicebot_crm.py
     Score: 216.0  |  LOC: 183  |  Functions: 11  |  Classes: 0
 3. execution/voicebot_calendar.py
     Score: 172.0  |  LOC: 157  |  Functions: 5   |  Classes: 0
```

```
DEAD CODE in voicebot (9 unreferenced definitions)

  execution/voicebot_crm.py
    - get_call_history()
    - update_appointment()
    - update_customer()
  execution/voicebot_sms.py
    - send_cancellation()
    - send_reminder()
```

```
CODE SMELLS in voicebot (53 issues)

Long functions (>50 lines) (6):
  voicebot_agent.py: run_tool() is 106 lines
  voicebot_agent.py: respond() is 61 lines

Deep nesting (>4 levels) (1):
  voicebot_agent.py: run_tool() has nesting depth 7
```

```
TEST COVERAGE MAP - voicebot

Coverage: 0/7 source files have a test file (0%)

No test file found:
  execution/voicebot_agent.py
  execution/voicebot_crm.py
  ...
```

---

## Setup

**1. Install dependencies**
```bash
pip install gitpython networkx radon mcp
```

**2. Register in Claude Code**

Add to `.mcp.json` in your project root:
```json
{
  "mcpServers": {
    "git-analyst": {
      "command": "python",
      "args": ["git_analyst/execution/server.py"],
      "cwd": "/absolute/path/to/your/workspace"
    }
  }
}
```

**3. Restart Claude Code**

The `mcp__git-analyst__*` tools will appear automatically.

**4. Use it**

Ask Claude anything:
> "Analyze the complexity of my repo at C:/Projects/myapp"
> "Find dead code in C:/Projects/myapp"
> "What are the biggest code quality issues in C:/Projects/myapp?"

---

## Tech stack

- **`gitpython`** — commit history traversal, churn analysis
- **`ast`** (stdlib) — Python file parsing, dead code detection, import graph
- **`networkx`** — directed import graph, cycle detection
- **`radon`** — cyclomatic complexity (used internally)
- **`mcp`** — FastMCP stdio transport

---

## Design decisions

**Lazy repo cache**
The server holds a `dict[str, git.Repo]` cache. Every tool calls `_get_repo(repo_path)` which populates the cache on first access. This means tool call order is never a concern — Claude can call any tool first and it will work. Multiple repos are supported simultaneously in the same session.

**Structured errors, not exceptions**
Every failure returns a dict Claude can reason about:
```python
{"error": "invalid_repo", "detail": "No .git found at /path", "partial_results": None}
{"error": "large_repo_capped", "detail": "200 files found, capped at 50", "partial_results": {...}}
```
A bare Python traceback is invisible to Claude. A structured error lets it explain the problem and suggest a fix.

**Risk score = churn x complexity**
`find_hotspots` doesn't just rank by commit count or complexity alone. A file changed 20 times that's 10 lines long is not a problem. A complex 400-line file touched every sprint is where real technical debt lives. The composite score surfaces that intersection.

**50-file cap on graph tools**
Graph algorithms are O(n²). `detect_coupling` caps at 50 Python files and reports the cap in output — so the tool never hangs on a large repo, and the caller always knows if results are partial.

**Dead code uses two-pass AST**
Pass 1 collects all public function and class names across the repo. Pass 2 collects every name referenced anywhere (calls, attributes, imports). The diff is the dead code. Private names (`_prefixed`) are excluded — they're intentionally internal.

---

## Limitations

- Python only — `.py` files only. JS/TS support planned.
- Dead code detection has false positives for: functions called via `getattr`, dynamically constructed names, and entry points (like Flask routes) that are called by a framework.
- Test coverage is file-name convention only (`test_foo.py` maps to `foo.py`). It does not analyse what is actually tested inside the file.
- Monorepos: commit paths are relative to the git root, so hotspot complexity cross-referencing may not match if the repo root differs from the path you pass.

---

## Author

[putman18](https://github.com/putman18) — [portfolio](https://putman18.github.io)
