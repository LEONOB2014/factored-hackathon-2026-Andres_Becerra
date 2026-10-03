# CLAUDE.md

@AGENTS.md

## Claude Code specifics

- Use plan mode for any change touching more than a few files, and get the plan approved
  before editing.
- Never run `git push` (branches or tags) without the maintainer approving that specific
  push in the conversation. Never commit in the main checkout or on `main`/`develop`.
- Work in a worktree under `../antigravity-worktrees/`; create one per branch.
- Keep project memory current: record new workflow rules and non-obvious gotchas, and
  update `AGENTS.md` in the same PR when a repository rule changes.
- Personal, uncommitted preferences go in `CLAUDE.local.md` (git-ignored).
