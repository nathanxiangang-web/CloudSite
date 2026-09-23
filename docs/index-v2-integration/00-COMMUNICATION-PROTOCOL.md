# CloudSite Index-V2 Integration Communication Protocol

> Status: Architecture governance standard
>
> Control issue: #223
>
> Applies to: Architect and all Codex workers participating in the CloudSite 1.0.0 × index-v2 integration.

## 1. Purpose

GitHub is the single source of truth for this project. Chat messages, local notes, and worker memory are not authoritative unless the architect converts them into a GitHub Issue, PR review, ADR, or this document.

The protocol exists to prevent:
- workers changing scope while implementing;
- parallel workers modifying the same ownership area without coordination;
- “done” claims without code/test evidence;
- repeated blind retries;
- accidental import of unrelated CloudSite 2.0 architecture into the 1.0.0 baseline;
- context loss between Codex sessions.

## 2. Authority and roles

### Project sponsor
The user decides product intent and whether the project continues or stops.

### Architect
The architect owns:
- scope freeze;
- architecture and compatibility contracts;
- task decomposition and dependency order;
- worker path ownership;
- acceptance criteria;
- PR review and merge recommendation;
- changes to the blueprint;
- final release gate.

Only the architect may mark a task `READY` or `ACCEPTED`.

### Codex worker
A worker owns implementation only inside the task contract. A worker may inspect adjacent code for understanding, but may not change adjacent scope without a change request.

A worker must never infer “while I am here” work.

## 3. Authoritative artifacts

Order of authority, highest first:

1. Accepted ADR / current integration blueprint.
2. Architect decision recorded in the task Issue or PR review.
3. Task Issue marked `READY`.
4. Accepted PR and its tests.
5. Worker comments and progress reports.

If two artifacts conflict, the higher item wins. The worker must report the conflict instead of choosing silently.

## 4. GitHub communication model

### Issue = work order
Every implementation task has exactly one Issue.

### Branch = execution workspace
One task normally maps to one worker branch.

Branch naming:

```text
worker/W<worker-number>/<task-id>-<short-slug>
```

Example:

```text
worker/W2/IDX-P2-003-v1-persistence-adapter
```

### Commit = auditable progress
Commit messages must describe the actual change and include the task ID when practical.

Recommended:

```text
feat(indexing): add v1 resource persistence adapter [IDX-P2-003]
test(indexing): cover interrupted scan resume [IDX-P3-002]
fix(indexing): prevent incomplete snapshot deletion [IDX-P4-001]
```

### PR = delivery unit
One task = one PR unless the architect explicitly authorizes a split.

Workers do not merge their own PRs.

## 5. Task state machine

```text
DRAFT
  ↓ architect
READY
  ↓ worker
ACK
  ↓
IN_PROGRESS
  ├─→ BLOCKED ──→ architect decision ──→ IN_PROGRESS / HOLD / CANCELLED
  ↓
DELIVERY
  ↓ architect review
CHANGES_REQUIRED / REBASE / ACCEPTED / REJECTED
  ↓
CLOSED
```

Architect commands:
- `DRAFT`: specification incomplete; no implementation.
- `READY`: worker may start.
- `HOLD`: stop all work and preserve state.
- `CHANGES_REQUIRED`: modify current PR only as requested.
- `REBASE`: update from the architect-approved integration base before further review.
- `ACCEPTED`: acceptance criteria met.
- `REJECTED`: implementation direction is not acceptable.
- `CANCELLED`: task no longer needed.

Worker signals:
- `ACK`: task understood and execution contract restated.
- `PROGRESS`: evidence-based checkpoint.
- `BLOCKED`: work cannot safely continue.
- `DELIVERY`: PR is ready for architect review.

## 6. Required task Issue contract

A task may be marked `READY` only when it contains all fields below.

```markdown
TASK: IDX-Px-xxx
STATUS: READY
OWNER: W1
BASE: <approved base branch>@<sha>
SOURCE: index-v2@<frozen sha, when applicable>

GOAL
<one measurable outcome>

BACKGROUND
<why the task exists>

IN SCOPE
- ...

OUT OF SCOPE
- ...

ALLOWED PATHS
- ...

FORBIDDEN PATHS
- ...

DEPENDENCIES
- task / PR / interface dependencies

COMPATIBILITY CONTRACT
- externally observable behavior that must remain unchanged

ACCEPTANCE CRITERIA
- [ ] ...
- [ ] ...

REQUIRED TESTS
- exact commands / test families

ROLLBACK
- how to disable or revert safely

DELIVERABLE
- expected PR contents and evidence
```

A worker must not begin from a title-only Issue.

## 7. Worker ACK format

Before modifying code, the worker posts:

```markdown
ACK <TASK-ID>

Base:
- branch:
- SHA:

Understanding:
- <one paragraph>

Planned changes:
- <paths/components>

Will not change:
- <explicit boundaries>

Test plan:
- <commands/tests>

Risks / assumptions:
- <none, or list>
```

If the base SHA has moved unexpectedly, the worker reports it and waits for `REBASE` or a new base decision.

## 8. Progress report standard

Report after a meaningful engineering boundary, not on a timer.

```markdown
PROGRESS <TASK-ID>

Completed:
- ...

Evidence:
- commit <sha>
- test <command>: PASS/FAIL

Next:
- ...

Risk/change request:
- none / details
```

Do not post “still working” without evidence.

## 9. Scope-change protocol

If implementation requires a file, schema, API, dependency, or behavior outside the task contract, stop and post:

```markdown
CHANGE REQUEST <TASK-ID>

Trigger:
- ...

Required scope expansion:
- ...

Why current contract cannot complete safely:
- ...

Alternatives:
1. ...
2. ...

Recommended minimum change:
- ...
```

No out-of-scope change is permitted until the architect updates the Issue or explicitly approves it.

## 10. Failure and retry rule

A worker may make at most two materially different implementation attempts for the same blocking problem without architect intervention.

After the second failed attempt, the worker must stop and report:

```markdown
BLOCKED <TASK-ID>

背景:
<what state/code/environment exists>

目的:
<what was being attempted>

执行:
1. Attempt 1 — action + evidence
2. Attempt 2 — action + evidence

结果:
<exact failure, logs/tests, suspected cause>

Current branch/commit:
- ...

Safe state:
- whether changes can be kept or should be reverted

Architect decision needed:
- ...
```

A third blind attempt is prohibited.

## 11. Delivery report standard

The worker opens a PR and posts to the task Issue:

```markdown
DELIVERY <TASK-ID>

PR:
- #...

背景:
- ...

目的:
- ...

执行:
- implementation summary

结果:
- behavior achieved

Changed paths:
- ...

Commits:
- ...

Tests:
- <exact command> — PASS
- <exact command> — PASS

Acceptance checklist:
- [x] ...

Known limitations:
- none / ...

Risk:
- low / medium / high + reason

Rollback:
- ...
```

“Tests pass” without commands/results is insufficient.

## 12. PR acceptance gates

A PR is not acceptable unless:

1. It targets the architect-approved integration branch.
2. It contains only task scope.
3. Required tests pass.
4. Existing 1.0.0 compatibility tests remain green for affected behavior.
5. No unrelated formatting/refactor churn is included.
6. No whole-branch merge or bulk cherry-pick from `index-v2` occurred.
7. Any new DB schema has migration, rollback/rebuild semantics, and tests.
8. Failure paths are tested when the task affects persistence, deletion, resume, or cutover.
9. PR description links the task Issue.
10. CI is green, or the architect explicitly records why a check is non-applicable.

## 13. Parallel-worker ownership rules

Workers may run in parallel only when path and contract ownership do not overlap.

Rules:
- Architect assigns ownership before `READY`.
- Two workers may read the same file.
- Two workers may not both modify the same file unless an explicit integration order is documented.
- Workers do not cherry-pick other worker branches on their own.
- Shared-interface changes are produced by the owner of that interface first; dependent workers rebase only after architect instruction.
- Cross-worker conflict resolution belongs to the architect/integration task, not an individual worker.

## 14. Architecture decision rule

Create an ADR when a decision is difficult to reverse or changes one of:
- DB ownership/schema;
- stable resource identity semantics;
- indexing snapshot/reconcile semantics;
- crash recovery/checkpoint semantics;
- external API compatibility;
- scheduler/cutover behavior;
- search consistency guarantees.

Minor implementation details stay in the task Issue/PR.

## 15. Integration-specific hard prohibitions

For this project:

- Do not merge `index-v2` into `main`.
- Do not cherry-pick a large sequence of V2 commits as a substitute for integration design.
- Do not import V2 Catalog, Automation, Delivery, UI, or unrelated modularization.
- Do not rewrite 1.0.0 authentication, shares, collections, user flows, preview, or download behavior.
- Do not change public API behavior merely to make V2 code easier to reuse.
- Do not remove the old index path before the new path passes the cutover gate.
- Do not perform destructive reconciliation from an incomplete scan.
- Do not declare production readiness from fake-provider tests alone where a real AList behavior is required.

## 16. Communication routing

- Project-wide architecture/scope: Issue #223.
- Task-specific discussion: task Issue.
- Code-specific review: PR review.
- CI/test failure: PR + exact workflow/job evidence.
- New architecture decision: ADR PR + reference from #223.

If a decision was made elsewhere, it must be copied into the correct GitHub artifact before workers act on it.

## 17. Definition of communication success

The process is working when a fresh Codex session can open the repository and, using only:
- this protocol;
- the blueprint;
- Issue #223;
- its assigned task Issue;

understand exactly what it may change, why, how to test it, and how to report completion without relying on hidden conversation context.
