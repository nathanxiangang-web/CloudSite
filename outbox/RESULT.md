# work02 D1 检索 + D2 专题 端到端测试结果

## 新增测试列表

| 文件 | 测试数 | 覆盖内容 |
|------|--------|----------|
| apps/api/tests/test_catalog_search_projection_e2e.py | 7 | D1 搜索投影一致性 E2E：outbox 入队→消费→FTS 可搜、崩溃重放幂等、旧 revision 不覆盖新数据、全量重建后人工条目可搜、fail-closed 禁用条目/禁用 root 立即搜不到、旧 /api/search 契约零改动 |
| apps/api/tests/test_catalog_search_route.py | 3 | D1 搜索 API 路由契约：q/content_type/tag/platform 筛选、别名匹配、无结果 suggestion、空查询 400 |
| apps/api/tests/test_collection_topic_e2e.py | 5 | D2 专题 E2E：CollectionItem 强类型（resource/catalog_entry）、NULL resource_id 不违反约束、专题字段 goal/audience/prerequisites/item_intro 读写、3 个种子专题可查询+幂等、移除条目后计数正确 |
| apps/web/tests/catalog-search.test.mts | 4 | 前端聚合搜索：条目/文件双数据源 URL 分区、分区可见性判定、条目/文件 href 前缀分离、条目按 content_type 标注 |

## 通过数

- 新增后端测试：15 个全部通过
- 新增前端测试：4 个全部通过
- 后端全量回归：491 个全部通过（含新增）
- 前端全量回归：40 个全部通过（含新增）

## 发现的 bug

无。新增测试与全量回归均未发现正式代码 bug，无需修复。

## 约束遵守

- 只新增测试文件，未修改任何正式代码
- 复用现有 fixture 模式（参考 test_catalog_search_service.py、test_collection_scope.py、test_catalog_routes.py）
- 未起长驻服务，未 docker build
