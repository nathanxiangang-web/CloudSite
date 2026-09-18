import json

# Patch bridge.ps1
path = '/home/nathan/codex-glm-bridge-repo/scripts/bridge.ps1'
with open(path) as f:
    content = f.read()

old = "Start-Process -FilePath $hostExe -ArgumentList $runnerArgs -WindowStyle $windowStyle -PassThru"
new = "if ($IsWindows) { Start-Process -FilePath $hostExe -ArgumentList $runnerArgs -WindowStyle $windowStyle -PassThru } else { Start-Process -FilePath $hostExe -ArgumentList $runnerArgs -PassThru }"

if old in content:
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print("bridge.ps1 patched successfully")
else:
    print("Pattern not found in bridge.ps1")

# Check task states
tasks = ['cs-b3-indexing-w01-20260917','cs-b2-testfix-w02-20260917','cs-b5-e2e-w03-20260917','cs-b6-docs-w04-20260917']
for t in tasks:
    s = json.load(open(f'/home/nathan/codex-glm-bridge-repo/tasks/{t}/state.json'))
    print(f"{t}: {s['status']} | {s.get('message','')}")