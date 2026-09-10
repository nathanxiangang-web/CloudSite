# work04 M3 验证记录

## 目标测试（TASK.md 指定 + 新增）
命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest \
  tests/test_collection_scope.py \
  tests/test_resource_detail_sibling_scope.py \
  tests/test_share_scope_and_home_cache.py -q
```
结果：**11 passed**

## 全量回归
命令：
```
cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q
```
结果：**476 passed**（基线 471 + 新增 5）

## 新增测试清单（test_share_scope_and_home_cache.py）
1. test_legacy_share_disabled_root_resource_returns_invalid_target
   — 旧分享接口对禁用根资源返回 SHARE_TARGET_INVALID
2. test_legacy_share_folder_children_scoped_to_folder_root
   — folder 分享 child 不跨根（同 parent_id 脏数据不混入）
3. test_home_cache_excludes_disabled_root_after_invalidation
   — 预热缓存后禁用根 + invalidate_home_cache 后不再展示禁用资源
4. test_admin_root_mapping_update_invalidates_home_cache
   — admin 修改 root-mapping 触发 invalidate_home_cache
5. test_admin_root_mapping_delete_invalidates_home_cache
   — admin 删除 root-mapping 触发 invalidate_home_cache

## 资源限制
未执行 docker build，未起长驻服务。
