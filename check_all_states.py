import json

tasks = [
    'cs-b3-indexing-w01-20260917',
    'cs-b2-testfix-w02-20260917',
    'cs-b5-e2e-w03-20260917',
    'cs-b6-docs-w04-20260917'
]

for t in tasks:
    s = json.load(open(f'/home/nathan/codex-glm-bridge-repo/tasks/{t}/state.json'))
    print(f"{t}:")
    print(f"  status={s['status']} attempt={s['attempt']}")
    print(f"  msg={s.get('message','')}")
    if s.get('commitSha'):
        print(f"  commit={s['commitSha'][:12]}")
    if s.get('worktreePath'):
        print(f"  worktree={s['worktreePath']}")
    print()