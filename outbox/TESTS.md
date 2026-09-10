# work01 B1 验证记录

## 后端

命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q
```

结果：
```
471 passed, 137 warnings in 79.12s (0:01:19)
```

说明：包含 schema_version 断言（已更新为 12）、迁移幂等、catalog/合集/站点等全量用例，全部通过。

## 前端

命令：
```
cd apps/web && corepack pnpm install --frozen-lockfile && corepack pnpm typecheck
```

结果：
```
> tsc --noEmit
（无错误输出，typecheck 通过）
```

说明：install 使用 frozen-lockfile，typecheck（tsc --noEmit）无类型错误。未跑 build（符合任务书要求）。

## 资源限制遵守

- 未并行跑多个重进程；未 docker build；未起长驻服务。
