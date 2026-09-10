# 验证执行记录

## 后端
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_search_service.py -q`
结果：8 passed

回归命令：`cd apps/api && python -m pytest tests/test_catalog_service.py tests/test_catalog_routes.py tests/test_catalog_metadata_service.py tests/test_catalog_metadata_routes.py tests/test_catalog_search_service.py -q`
结果：43 passed

迁移/schema 命令：`cd apps/api && python -m pytest tests/test_catalog_state_migration.py tests/test_catalog_c3_metadata_migration.py tests/test_catalog_release_asset_schema.py -q`
结果：22 passed

旧 search 契约命令：`cd apps/api && python -m pytest tests/test_search_fts_delta.py tests/test_search_recovery.py -q`
结果：15 passed

## 前端
命令：`corepack pnpm install --frozen-lockfile`
结果：Done in 1s

命令：`corepack pnpm typecheck`
结果：通过（tsc --noEmit 无错误）

## 资源限制遵守
未并行跑多个重进程；未 docker build；未起长驻服务。
