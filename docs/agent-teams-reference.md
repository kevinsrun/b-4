# Agent Teams: Master Reference

A working reference for designing, spawning, and running Claude Code agent teams well. It is distilled from the official docs (https://code.claude.com/docs/en/agent-teams, fetched 2026-10-03) and organized for use while planning a team.

> Agent teams are **experimental**. Behavior and version-gated details below may change. When something here conflicts with current behavior, trust current behavior and update this file.

---

## 1. Quick decision: team, subagents, or solo?

Ask in order:

1. **Is the work sequential, heavily interdependent, or in the same files?** → Single session. A team adds overhead and causes overwrites.
2. **Do the workers only need to return a result, with no talk between them?** → **Subagents**. They're cheaper because results are summarized back to the caller.
3. **Do the workers need to share findings, challenge each other, or coordinate on their own?** → **Agent team**.
4. **Is the work split across sessions you run yourself?** → Cross-session messaging, or git worktrees with manual sessions.

| | Subagents | Agent teams |
|---|---|---|
| Context | Own window; result returns to caller | Own window; fully independent |
| Communication | Return result to caller (named subagents can message each other) | Teammates message each other directly |
| Coordination | Main agent manages everything | Self-coordinate via messages + shared task list |
| Best for | Focused tasks where only the result matters | Complex work needing discussion/collaboration |
| Token cost | Lower | Higher, roughly linear in the number of active teammates |

**Strong team use cases**
- **Research & review**: parallel investigation of different aspects, then cross-challenge.
- **New modules/features**: each teammate owns a separate piece.
- **Debugging with competing hypotheses**: parallel theories; adversarial debate fights anchoring.
- **Cross-layer changes**: frontend / backend / tests each owned by one teammate.

**Poor team use cases:** routine tasks, sequential pipelines, same-file edits, many dependencies.

---

## 2. Enabling & prerequisites

```json
// .claude/settings.local.json (already set in this project)
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

- Without the flag: no team is set up, no team dirs are written, and no teammates are spawned or proposed.
- **Requires an interactive session.** In `-p` / headless / Agent SDK sessions no teammates spawn, and a named subagent runs as an ordinary subagent.
- **Side effect:** while enabled, *any* Agent-tool call with a `name` launches a **teammate**, not a subagent. The exceptions are forks and calls that pass `isolation`. Claude names subagents on its own so it can message them later, which means teams can form unintentionally. There is **no confirmation prompt**.
  - To get a plain subagent while teams are enabled, omit `name`, or pass `isolation` on the call.
  - To turn teams off: set the variable to `"0"`. This applies live on save, with no restart. Higher-precedence sources (project, local, `--settings`, managed) can still override a user-level `0`.
  - Settings precedence, lowest to highest: user → project → local → `--settings` → managed.

---

## 3. Architecture (what actually exists)

| Component | Role |
|---|---|
| **Team lead** | The main session. It spawns teammates and coordinates. It is **fixed for the session's lifetime**. |
| **Teammates** | Separate, full Claude Code instances with independent context windows. |
| **Task list** | Shared work items with states `pending` → `in progress` → `completed`, plus dependencies. |
| **Mailbox** | Per-agent JSON inbox used for messaging. |

**Files on disk** (team name = `session-` + first 8 chars of the session ID):
- Team config: `~/.claude/teams/{team-name}/config.json`. Runtime state. **Do not edit or pre-author it**, because it gets overwritten. It has a `members` array (name, agent ID, agent type; the lead is always `team-lead`). Teammates can read it to discover each other. It is removed when the session ends.
- Inboxes: `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`. Malformed entries are reported and dropped, and valid ones are still delivered.
- Tasks: `~/.claude/tasks/{team-name}/`. These **persist** locally, survive resume, and are retained per `cleanupPeriodDays`.
- No project-level team config exists. A file like `.claude/teams/teams.json` in the repo is just an ordinary file. **Reusable roles go in subagent definitions** (`.claude/agents/*.md`), not team config.

**Task mechanics**
- A pending task with unresolved dependencies can't be claimed. When a dependency completes, its dependents unblock automatically.
- Claiming uses file locking, so there are no double-claims.
- The lead can assign tasks explicitly, or teammates self-claim the next unassigned, unblocked task when they finish one.
- Agents without the Task tools coordinate via messages only.

**Messaging**
- Delivery is automatic, so the lead doesn't need to poll.
- **There is no broadcast.** Send one message per recipient.
- Address teammates by name. Any teammate can message any other.
- A message counts as sent only if the write to the recipient's mailbox succeeds; otherwise the sender gets an error.
- **Idle notifications:** when a teammate stops, the lead is notified automatically and the notification includes the teammate's final answer. On an API error, the teammate notifies the lead of the failure with the error text.
- Messaging a stopped in-process teammate revives it in the same session, with its saved conversation and the message as its next prompt. This does not work after `/resume`.

---

## 4. Context: what a teammate does and doesn't know

**Loaded automatically:** CLAUDE.md, MCP servers, and skills (same as a regular session). If the lead was started with `--setting-sources`, teammates use the same restricted list.

**NOT inherited:** the lead's conversation history. **The spawn prompt is the teammate's entire task context.**

→ Every spawn prompt must be self-contained: goal, scope/paths, relevant facts already discovered, constraints, file ownership, deliverable format, and who to talk to.

---

## 5. Spawning: models, roles, plan mode

### Model selection (first match wins)
1. A model named in the spawn prompt for that teammate.
2. The subagent definition's `model` (`inherit` = the lead's model).
3. `CLAUDE_CODE_SUBAGENT_MODEL`, if set to something other than `inherit`.
4. The lead's current model.

- `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` skips sources 1 and 2.
- `teammateDefaultModel` is **removed** and ignored. Name the model in the prompt instead.
- The org's `availableModels` allowlist can substitute a different model: the newest permitted version of the family, or else the lead's model.
- Teammates inherit the lead's **effort level** by default.
- A teammate's model and fast mode are **fixed at spawn**. `/model` and `/fast` from a teammate view affect the lead only.

**Model strategy:** use the strongest model for teammates that reason, architect, or adjudicate debates. Use a cheaper or faster model (for example Sonnet or Haiku) for mechanical, well-specified work like parallel refactors, test writing, or search.

### Reusable roles via subagent definitions
Reference a subagent type from project, user, managed, or plugin scope when spawning ("Spawn a teammate using the `security-reviewer` agent type to…"). What carries over:

| Definition field | Applied to teammate? |
|---|---|
| `tools` | Yes. Restricts the toolset. In-process teammates also get `SendMessage` plus the Task tools (`TaskCreate/Get/List/Update`). |
| `model` | Yes, if the spawn prompt names no model. |
| `disallowedTools` | In-process only. `SendMessage` and the Task tools can't be removed. |
| `effort` | In-process only. |
| Body (system prompt) | In-process: **appended** to the default system prompt. Split-pane: **replaces** it. |
| `skills` | **No.** Teammates load skills from project and user settings. |
| `mcpServers` | Split-pane only. In-process teammates ignore it. |

Revived teammates re-apply a project `.claude/agents/` definition **only if that exact folder is trusted**; a trusted parent folder doesn't count. If the folder isn't trusted, the teammate comes back without the definition's tools or instructions.

### Plan-first teammates
Put the **lead** in plan mode *before* spawning, and the teammate then works read-only until its plan is ready. The plan approval request is **auto-approved by the lead session without review**, so this is a "think first" step, not a human review gate. Edits and commands afterward still go through normal permission prompts.

---

## 6. Permissions & trust

- Teammates start with the **lead's permission mode**. The exception is `dontAsk`, which is not inherited. `--dangerously-skip-permissions` on the lead applies to all teammates.
- Permission modes can't be set per teammate at spawn. They can be changed per teammate afterward.
- Teammate permission prompts **surface in the lead session**. **Pre-approve common operations** in the permission settings before spawning to avoid a flood of prompts.
- Inter-agent messages are labeled as coming from another Claude session, not from the user. A teammate **cannot** grant consent or approve prompts on the user's behalf, and a denied action can't be laundered through another teammate.
- In auto mode, the classifier treats relayed approval claims as untrusted and screens every inter-agent message, including protocol messages. Blocked messages never arrive.

---

## 7. Display & control

**Display modes** (`teammateMode` in `~/.claude/settings.json`, or the `--teammate-mode` flag):
- `"in-process"` (default): works in any terminal.
- `"auto"`: split panes if already inside tmux or in iTerm2 with the `it2` CLI; otherwise in-process.
- `"tmux"`: split panes; auto-detects tmux vs. iTerm2.
- `"iterm2"`: native iTerm2 panes. Requires the `it2` CLI and iTerm2 → Settings → General → Magic → Enable Python API.
- **Split panes are NOT supported in VS Code's integrated terminal, Windows Terminal, or Ghostty.** In VS Code, use in-process mode.

**In-process controls (agent panel below the prompt):**
- ↑/↓ selects a teammate · **Enter** views its transcript and messages it · **Esc** clears the selection, or interrupts the teammate's turn while you're viewing it · **x** stops the selected teammate · **Ctrl+T** toggles the task list.
- Idle rows hide 30s after the *whole panel* goes idle. The teammate is still alive, and messaging it by name brings it back.
- When more than three teammates are idle, the extras collapse into an `N idle agents` row; Enter expands it.
- While viewing a teammate, plain text and skills go to the teammate, and built-in commands go to the lead. `/compact`, `/clear`, and `/rewind` ask for confirmation.

**Shutdown:** "Ask the `<name>` teammate to shut down". The teammate can approve or reject with a reason. It finishes its current request or tool call first, so shutdown can be slow. Shared directories are cleaned up automatically when the session ends.

---

## 8. Quality gates with hooks

| Hook | Fires when | Exit code 2 effect |
|---|---|---|
| `TeammateIdle` | A teammate is about to go idle | Sends feedback and **keeps it working** |
| `TaskCreated` | A task is being created | **Blocks creation** and sends feedback |
| `TaskCompleted` | A task is being marked complete | **Blocks completion** and sends feedback |

Typical uses:
- `TaskCompleted` runs tests or lint and refuses completion until they pass.
- `TeammateIdle` checks that the deliverable file exists or that the teammate's tasks are all closed.
- `TaskCreated` enforces task-naming or sizing conventions.

---

## 9. Designing an efficient team (playbook)

### Size
- **Start with 3–5 teammates.** Token cost scales linearly, coordination overhead grows, and returns diminish.
- 15 independent tasks → about 3 teammates. **Aim for 5–6 tasks per teammate** so the lead can rebalance if someone gets stuck.
- Three focused teammates usually beat five scattered ones. Scale up only when the work is truly parallel.

### Task granularity
- Too small: coordination costs more than the work.
- Too large: long runs without check-ins waste effort when the direction is wrong.
- Right size: a self-contained unit with a clear deliverable (a function, a test file, a review, a findings section).
- If the lead creates too few tasks, tell it to split the work smaller.

### Ownership
- **One owner per file.** Two teammates editing the same file overwrite each other. Partition by directory, layer, or module, and state the ownership in each spawn prompt.
- Integration points (shared types, interfaces) should be decided up front by the lead, or owned by exactly one teammate who notifies the others.

### Naming
- Tell the lead what to call each teammate ("name them `ux`, `arch`, `critic`"). Predictable names make later steering, messaging, and shutdown easy.

### Spawn prompt checklist
Each spawn prompt should include:
- [ ] **Role/lens**: what this teammate is responsible for, distinct from the others
- [ ] **Scope**: exact paths, modules, PR number, or question
- [ ] **Known facts**: anything the lead already learned (the teammate has no history)
- [ ] **Constraints**: files it owns or must not touch, tech choices, style rules
- [ ] **Collaboration**: which teammates to message, and when (e.g. "send interface changes to `backend`")
- [ ] **Deliverable**: exact format and location (findings doc section, file, severity-rated list)
- [ ] **Done criteria**: how it knows it's finished (tests pass, task marked complete)
- [ ] **Model**: if it should differ from the default

### Lead discipline
- **The lead coordinates; it doesn't implement.** If it starts doing teammates' work, tell it: "Wait for your teammates to complete their tasks before proceeding."
- Watch for the lead declaring victory early, and tell it to keep going until every task is actually complete.
- Monitor and steer. Unattended teams drift.
- Synthesize as results arrive. Idle notifications carry each teammate's final answer.

### Starting out
Start with research or review tasks that have clear boundaries and need no code changes (PR review, library research, bug investigation). Move to parallel implementation once the patterns are familiar.

---

## 10. Prompt templates

**Multi-lens exploration**
```text
I'm designing <thing>. Spawn three teammates to explore this from different angles:
one on UX (name: ux), one on technical architecture (name: arch), one playing
devil's advocate (name: critic). Have critic challenge ux and arch directly.
Synthesize a recommendation when all three are done.
```

**Parallel code review**
```text
Spawn three teammates to review PR #<n>:
- security: security implications
- perf: performance impact
- tests: test coverage gaps
Each reports findings with severity ratings. Synthesize a single ranked list.
```

**Competing hypotheses debugging**
```text
<Symptom description>. Spawn 5 teammates, each investigating a different hypothesis.
Have them message each other to try to disprove each other's theories, like a
scientific debate. Update <findings doc> with whatever consensus emerges.
```
Why it works: sequential investigation anchors on the first plausible theory, while adversarial parallel investigators are more likely to converge on the real root cause.

**Parallel implementation with ownership**
```text
Spawn 3 teammates using Sonnet:
- api (owns src/api/**): implement endpoints per <spec>
- ui (owns src/ui/**): build the screens per <spec>
- tests (owns tests/**): write integration tests against the contract in <file>
The shared contract is in <file> and only api may change it; api must message ui
and tests about any change. Nobody edits files outside their ownership.
```

**Reusable role**
```text
Spawn a teammate using the security-reviewer agent type to audit src/auth/.
Context: JWT in httpOnly cookies; focus on token handling, session management,
input validation. Report issues with severity ratings.
```

**Self-contained spawn prompt (good context example)**
```text
Spawn a security reviewer teammate with the prompt: "Review the authentication module
at src/auth/ for security vulnerabilities. Focus on token handling, session
management, and input validation. The app uses JWT tokens stored in
httpOnly cookies. Report any issues with severity ratings."
```

---

## 11. Costs & caching

- Each teammate is a full Claude instance, so tokens scale with active teammates. This is worth it for research, review, and new features, but not for routine work.
- The prompt cache for in-process teammates defaults to a **5-minute TTL**, including on subscriptions. Set `subagentPromptCacheTtl: "1h"` to keep it longer. 1-hour cache writes cost more, so this pays off when teammates idle for more than 5 minutes between turns.
- Shut down teammates that are done instead of leaving them idle.

---

## 12. Limitations (design around these)

- **No resume for in-process teammates.** `/resume` and `/rewind` don't restore them, and after a resume the lead may message ghosts. Fix it by telling the lead to spawn fresh teammates. (Tasks do persist.)
- **Task status can lag.** Teammates sometimes forget to mark tasks complete, which blocks dependents. Verify the work and update the status, or have the lead nudge the teammate. A `TeammateIdle` hook can enforce this.
- **Slow shutdown**, because the current request or tool call finishes first.
- **One team per session**, scoped to it. There are no named or shared teams.
- **No nested teams.** Only the lead manages the team.
- **No background subagents from in-process teammates.** `background: true` definitions error, and `run_in_background: true` errors or runs in the foreground.
- **The lead is fixed** and can't be transferred.
- **Permissions are set at spawn** from the lead's mode, and are adjustable per teammate only afterward.
- **Split panes need tmux or iTerm2.** They don't work in the VS Code terminal, Windows Terminal, or Ghostty.

---

## 13. Troubleshooting

| Symptom | Fix |
|---|---|
| Teammates not appearing | Check the agent panel (↑/↓). Hidden idle rows aren't stopped, so message the teammate by name. The task may be too simple, so ask explicitly for an "agent team". For split panes, check `which tmux`, or `it2` plus the Python API. |
| Got subagents instead of a team | The agent panel shows both. Ask again and explicitly request an agent team. |
| Got teammates instead of subagents | Named Agent calls become teammates while enabled. Set the flag to `0` (live reload), or omit `name` / pass `isolation`. |
| Too many permission prompts | Pre-approve common commands in permission settings before spawning. |
| Teammate stopped after an error | View its transcript, then give it new instructions or spawn a replacement. A message wakes a teammate that's waiting on an API retry. |
| Lead stopped early | Tell it to keep going until all tasks are complete. |
| Lead is doing the work itself | "Wait for your teammates to complete their tasks before proceeding." |
| Task stuck as blocked | The dependency is probably done but not marked. Verify it and update the status. |
| Orphaned tmux session | `tmux ls`, then `tmux kill-session -t <name>` |
| Mailbox write failed | Disk full or the directory isn't writable. Check `~/.claude/teams/`. |

---

## 14. Project notes (b-4)

- Agent teams are enabled via `.claude/settings.local.json`.
- The editor is VS Code, so **use in-process mode**; split panes aren't supported in the VS Code terminal.
- Reusable teammate roles belong in `.claude/agents/<role>.md`. Remember that `skills` in a definition doesn't apply to teammates.

## Related
- Subagents: https://code.claude.com/docs/en/sub-agents
- Cross-session messaging: https://code.claude.com/docs/en/cross-session-messaging
- Hooks: https://code.claude.com/docs/en/hooks
- Costs: https://code.claude.com/docs/en/costs#agent-team-token-costs
- Git worktrees (manual parallel sessions): https://code.claude.com/docs/en/worktrees
