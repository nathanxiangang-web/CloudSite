# 验证执行记录

## 后端

### 任务书指定命令
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_service.py -q`
结果：20 passed

### C4 新增自测
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_follow_service.py -q`
结果：9 passed

覆盖场景：
- 关注/取关/状态查询
- 关注幂等
- 取关后重新关注自动重新订阅
- 未发布条目不可关注
- 我的关注列表含最新发布版本摘要
- 发布 release 通知关注者且按 (release_id, user_id) 去重
- update_catalog_release publish 触发通知
- 普通更新（非 publish）不触发通知
- 退订用户不收到通知

### 迁移与 schema 版本
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_state_migration.py tests/test_schema_version.py -q`
结果：9 passed（含空库建表、v3 旧库升级到 v10、重复 init 幂等、schema_version 记录）

### 后端合并套件
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_service.py tests/test_catalog_follow_service.py tests/test_catalog_state_migration.py tests/test_schema_version.py -q`
结果：29 passed

## 前端

命令：`corepack pnpm install --frozen-lockfile && corepack pnpm typecheck`
结果：install Done in 1.4s；typecheck 通过（tsc --noEmit 无错误）

## 资源限制遵守
- 未并行跑多个重进程
- 未 docker build
- 未起长驻服务
