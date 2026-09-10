# work04 M3 发布范围统一过滤 — 结果

## 修改文件列表
1. `apps/api/cloudsite/routers/shares.py` — 旧兼容接口 `/api/shares/{token}` 统一范围过滤
2. `apps/api/cloudsite/routers/admin/content_roots.py` — root-mapping 写操作失效首页缓存
3. `apps/api/tests/test_share_scope_and_home_cache.py` — 新增回归测试（5 例）

## 核心改动

### routers/shares.py: public_share（旧兼容接口）
- 在返回目标前统一调用 `target_valid_for_share` 判断发布范围，禁用根的目标
  返回 `404 {"code": "SHARE_TARGET_INVALID"}` 而非泄漏资源元数据。
- folder 分享的 `child_folders`/`child_resources` 查询增加
  `Folder/Resource.root_mapping_id == target.root_mapping_id` 限定，跨 root
  同 parent_id 的脏数据不再混入。

### routers/admin/content_roots.py: 缓存失效
- `add_root_mapping`/`update_root_mapping`/`delete_root_mapping` 在 commit 后
  调用 `invalidate_home_cache()`，确保禁用/启用/删除根后首页预热缓存立即失效，
  下次请求按新范围重新生成，不再继续展示已下架资源。

### 已具备的过滤（本次确认无需改动）
- `routers/resources.py` 关联对象（related/previous/next）已限定
  `root_mapping_id == row.root_mapping_id` 且 `root_mapping_id.in_(enabled_ids)`。
- `services/collections.py` 列表计数与 item 已按 `enabled_root_ids` 过滤。
- `routers/home.py` 首页计数/最近/热门已按 `enabled_ids` 过滤。

## 尚存风险
- 302 下载跳转与已下载副本不在本次修复范围（手册约束）。
- collection 分享若含部分禁用根 item，旧接口现返回 invalid_target（与新版分享
  `build_share_target_payload` 行为一致），属收紧而非扩大范围。
- `_storage_info_cache`/`_alist_connection_cache` 与根启用状态无关，未触动。
