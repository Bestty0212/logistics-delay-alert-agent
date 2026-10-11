# Project rules
- Read docs/design.md before any change; it is the spec. If something is unclear or conflicts with it, ask instead of guessing.
- Python 3.13 in .venv; PostgreSQL in Docker. Do not add dependencies or frameworks unless I ask.
- Never invent dataset column names: inspect the real CSV header first.
- Never store or print customer personal information. The columns dropped in section 3 of the design doc must not exist in any table.
- The agent's database role is read-only; no agent tool may modify data.
- Never commit secrets or raw data. Use environment variables and .gitignore.
- Write pytest tests for every function you add.
- Keep each change small. After each task, summarize what you changed and why in plain English, and list every assumption you made.
- Do not modify anything under data/, and do not edit docs/design.md without asking me.
