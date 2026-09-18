import json

for t in ['cs-b5-e2e-w03-20260917','cs-b6-docs-w04-20260917']:
    s = json.load(open(f'/home/nathan/codex-glm-bridge-repo/tasks/{t}/state.json'))
    print(f"{t}: status={s['status']} attempt={s['attempt']} msg={s.get('message','')}")
    if s.get('commitSha'):
        print(f"  commit={s['commitSha'][:12]}")
    print()