# Git Repository Analyst MCP - Directive

## What it is
Four tools that answer the questions every developer has when opening an unfamiliar codebase: what's complex, what breaks constantly, who's doing what, and what depends on what. Runs locally against any Git repo, zero paid APIs.

## Tools

| Tool | Question it answers |
|---|---|
| `analyze_complexity_tool` | Which files are hardest to understand? |
| `find_hotspots_tool` | Which files are both complex AND constantly changing (highest risk)? |
| `summarize_commits_tool` | What has this team been doing, and how? |
| `detect_coupling_tool` | What does everything depend on, and are there circular imports? |

## Usage
Pass `repo_path` as an absolute path to any local Git repo root:
- `C:/Users/you/myproject`
- `C:/Program Files/Projects/voicebot`

## Design decisions (for interview explanation)
- **Lazy repo cache**: `_get_repo()` caches `git.Repo` objects by path — tool call order never matters, multiple repos work simultaneously
- **Structured errors**: all failures return `{"error": "type", "detail": "...", "partial_results": {...}}` so Claude can reason about failures instead of getting a traceback
- **Risk score = churn x complexity**: hotspots aren't just "changed often" or "complex" — they're the intersection, which is where real technical debt lives
- **50-file cap on detect_coupling**: graph algorithms are O(n²); cap prevents hanging on large repos, cap is communicated in output

## Known limitations
- Only analyzes `.py` files — JavaScript, TypeScript, etc. not supported
- Commit paths are relative to the git root, so monorepos (like this Projects workspace) may show cross-project paths in hotspots
- Circular import detection uses simple cycle detection — transitive cycles through stdlib modules will appear
