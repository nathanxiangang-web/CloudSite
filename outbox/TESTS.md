# work02 验证命令与结果

## 1. 后端新增测试（TASK.md 验证命令）

命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_search_projection_e2e.py tests/test_collection_topic_e2e.py -q
```
结果：12 passed（含 test_catalog_search_route.py 共 15 passed）

完整新增测试运行：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_search_projection_e2e.py tests/test_collection_topic_e2e.py tests/test_catalog_search_route.py -q
```
结果：**15 passed, 20 warnings in 6.24s**

## 2. 后端全量回归

命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q
```
结果：**491 passed, 163 warnings in 83.14s**

## 3. 前端测试

命令：
```
cd apps/web && node --test tests/*.test.mts
```
结果：**40 pass, 0 fail**（含新增 catalog-search.test.mts 4 个）

## 4. 资源限制遵守

- 未执行 docker build
- 未起长驻服务
- 仅用临时 sqlite engine + httpx ASGITransport 走真实 FastAPI 路由
