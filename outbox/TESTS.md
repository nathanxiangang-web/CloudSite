# work02 验证记录

## 后端
命令：`cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q`
结果：**471 passed, 137 warnings in 79.90s**（全绿）

相关子集快速验证：
`python -m pytest -q tests/test_collection_input.py tests/test_collection_scope.py tests/test_schema_version.py tests/test_admin_route_matrix.py tests/test_admin_route_inventory.py`
结果：19 passed

## 前端
命令：`cd apps/web && corepack pnpm typecheck`
结果：**tsc --noEmit 通过（无错误）**

## 资源限制遵守
- 未并行跑多个重进程（后端全量与前端 typecheck 串行）。
- 未执行 docker build，未起长驻服务。
- 前端未跑 build（按任务书要求）。
