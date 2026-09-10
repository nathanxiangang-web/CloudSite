# work01 验证命令与结果

## 1. 后端三个测试文件
命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest tests/test_catalog_download_route.py tests/test_catalog_admin_crud_route.py tests/test_presentation_route.py -q
```
结果：**17 passed in 3.44s**

## 2. 后端全量回归
命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q
```
结果：**493 passed, 143 warnings in 80.96s**

## 3. 前端全量
命令：
```
cd apps/web && corepack pnpm install --frozen-lockfile && corepack pnpm test
```
结果：
- pnpm install：Done in 442ms
- pnpm test：**44 pass, 0 fail**（含新增 catalog-delivery.test.mts 8 个）

## 资源限制遵守
- 未执行 docker build
- 未启动长驻服务
- 仅使用内存 SQLite（sqlite+aiosqlite:///:memory:）与 httpx ASGITransport
