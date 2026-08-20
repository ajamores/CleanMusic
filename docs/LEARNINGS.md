# Learnings

Paid-for mistakes, so no agent repeats them. One entry per failure, **trigger-first** —
a lesson only helps if you recognize the situation before you're in it.

Keep this short and curated. An entry earns its place only if repeating the mistake would
actually cost something; prune ones that a guardrail (a pin, a CI check, a type) now prevents
mechanically. A landfill of lessons gets ignored exactly like a bloated board does.

Format:

```
## <short title>
- Trigger: <the situation, before the mistake>
- Failure (<date>): <what went wrong>
- Rule: <what to do instead>
```

---

## yt-dlp / shazamio on Python 3.14
- Trigger: creating the venv, or a `shazamio-core` build fails from source
- Failure (2026-08-20): `uv venv` defaulted to Python 3.14; `shazamio-core` ships no 3.14 wheel and its Rust build died, breaking the install.
- Rule: use Python 3.10/3.11 (3.11 preferred — `yt-dlp` deprecates 3.10). Now pinned in `.python-version`, so `uv` picks it automatically. See `docs/DEVELOPMENT.md` for setup.

## Worktree agents branch from the pushed remote, not local HEAD
- Trigger: fanning out parallel worktree agents right after a local prep commit (a seam-widening refactor, a shared helper) that hasn't been pushed
- Failure (2026-08-20): committed an engine refactor to local `main` (`8001f8f`), then launched three worktree agents to build on those new seams. Every worktree branched from `origin/main` (the last *pushed* commit), so the refactor was invisible; all three rebuilt on the old structure and each independently re-touched the function the refactor was meant to isolate.
- Rule: before fanning out worktree agents, **push** any prep commit they depend on (`git push origin main`), or confirm the worktree base includes it (`git merge-base --is-ancestor <sha> <worktree-branch>`). A local-only commit does not reach a worktree.
