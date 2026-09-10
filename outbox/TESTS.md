# work01 C2 验证记录

## 后端

命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_release_asset_schema.py tests/test_catalog_routes.py -q
```

结果：
```
............                                                             [100%]
12 passed in 3.30s
```

覆盖：
- test_catalog_release_asset_schema.py：fresh init 达到 schema v8 并创建 language/build_label 列与默认值；synthetic v6 升级到 v8 保留 C1 行；重复 init 幂等；同条目第二个推荐 release 被部分唯一索引拒绝；显式推荐不依赖版本字符串比较；x64/arm64 asset 可区分查询；stable/beta/historical 共存。
- test_catalog_routes.py：catalog 路由注册、输入 schema 校验、真实创建/绑定/发布/公开读集成。

## 前端

命令：
```
cd apps/web && corepack pnpm install --frozen-lockfile
cd apps/web && corepack pnpm typecheck
```

结果：tsc --noEmit 无错误输出，typecheck 通过。

## 未执行（按 TASK.md 约定）

- 未跑前端 build / Docker 构建（内存受限，TASK.md 明确不跑）。
- 未起长驻服务做端到端下载 302 实测。
- 完整测试由架构师统一补。
