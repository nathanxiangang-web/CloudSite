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
    print(f"  message={s.get('message','')}")
    print(f"  commitSha={s.get('commitSha','N/A')}")
    print(f"  sessionId={s.get('sessionId','N/A')}")
    wt = s.get('worktreePath', '')
    print(f"  worktree={wt}")
    print()