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
