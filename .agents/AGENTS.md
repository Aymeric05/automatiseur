# Twitch Auto Clipper — Agent Rules

These rules apply to every agent and every conversation in this workspace.
They are the behavioral contract. Read them before doing anything else.

---

## 1. Source of Truth

The authoritative sources of truth are, in this order:

1. **The repository filesystem** — actual source files, `pyproject.toml`, `tests/`
2. **`.agents/state/pipeline-state.json`** — current pipeline stage and active task
3. **`.agents/state/handoffs/`** — structured reports written by the previous agent
4. **Git state** — `git status`, `git diff`, `git log --oneline -10`

Do **not** rely on the previous conversation's history or memory.
Always re-read the state files at the start of every session.

---

## 2. Role Boundaries

| Role | May modify application code? | May run tests? | May write handoff? |
|---|---|---|---|
| Orchestrator | ❌ Never | ✅ Read-only inspection | ✅ Updates `pipeline-state.json` |
| Developer | ✅ Yes, when explicitly tasked | ✅ Focused tests only | ✅ `developer-report.md` |
| QA | ❌ No (only test files if missing) | ✅ Full test suite | ✅ `qa-report.md` |
| Reviewer | ❌ Never | ❌ No | ✅ `reviewer-report.md` |

**Application code** means anything under `src/`. Test files under `tests/` may be
created or modified by QA only, and only when tests are explicitly missing.

---

## 3. Mandatory First Steps (Every Agent, Every Session)

Before doing any work, every agent must:

1. Read `.agents/state/pipeline-state.json`
2. Read the relevant handoff file(s) from `.agents/state/handoffs/` if they exist
3. Run `git status` and `git log --oneline -10` to understand the current repo state
4. **Never recreate functionality that already exists.** Inspect `src/` before assuming anything is missing.

---

## 4. Sequential Work — No Concurrent File Edits

Agents work **sequentially**. Only one agent modifies files at a time.
If you are an Orchestrator reading this, do not instruct two roles to work in parallel
on the same files.

---

## 5. Crash Safety and Resumption

Every agent must write its output **before stopping**, even if the task is incomplete.
Write a partial report to the handoff file with a `status: partial` field.
The next agent will detect this and resume from the last safe checkpoint.

If you reach a context or quota limit, write whatever you have completed so far
to the handoff file, set `status: partial`, and update `pipeline-state.json`
with `"last_safe_checkpoint"` describing where to resume.

---

## 6. Never Modify Application Code Silently

If a code change is necessary, it must be:
- Explicitly requested in `pipeline-state.json` under `"current_task"`
- Performed only by the Developer role
- Limited to the minimum change needed

Do not refactor, rename, or restructure code unless that is the explicit task.

---

## 7. Handoff Protocol

When your work is complete, write a structured Markdown report to
`.agents/state/handoffs/<role>-report.md` using this format:

```markdown
# <Role> Report

**Status:** complete | partial | failed
**Stage:** <pipeline stage name>
**Task:** <what was requested>

## Summary
<What was done, concisely>

## Findings / Changes
<Bullet list of specific findings or files changed>

## Next Step Recommendation
<What the Orchestrator should do next>

## Blockers (if any)
<Anything that prevented completion>
```

Then update `.agents/state/pipeline-state.json` with the new state.
