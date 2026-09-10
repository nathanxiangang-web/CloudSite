# work03 M1 备份恢复修复 — 验证结果

## 实际执行的验证命令与结果

### 脚本回归
```
$ bash scripts/tests/test-backup-hardening.sh
ALL TESTS PASSED (exit 0)
```
覆盖：归档权限 0600、无残留临时 db、正常归档验证、不安全路径拒绝、缺失文件拒绝、损坏 db 拒绝、恢复默认拒覆盖、--force 回滚副本、恢复后 quick_check、.env 匹配、容器内在线备份失败即停、**WAL 一致性（offline backup 保留已提交 WAL 行）**、**验证器缺失明确失败**、**manifest 存在**、**manifest 篡改校验和拒绝**、**Docker 状态未知时备份失败**。

```
$ bash scripts/tests/test-backup-content-roundtrip.sh
ALL TESTS PASSED (exit 0)
```
覆盖：备份创建、归档存在、验证接受、恢复完成、恢复后业务哨兵匹配（instance_id/site_name/users/resources/folders 精确值）、源 fixture 自洽、篡改值拒绝、删除资源行拒绝、无 --force 拒覆盖、**孤儿资源关系拒绝**、**业务归档验证器缺失失败**。

```
$ bash scripts/tests/test-backup-custom-data-path.sh
ALL TESTS PASSED (exit 0)
```
覆盖：自定义数据路径备份/恢复、默认 data/ 不受影响、归档可移植布局、导出优先级、不支持语法/空/遍历/根路径 fail-closed、归档内绝对路径恢复拒绝。

### 后端
```
$ cd apps/api && /home/nathan/CloudSite/.venv-workers/bin/python -m pytest -q
471 passed, 137 warnings in 76.64s
```

### 资源限制遵守
- 未执行 docker build
- 未启动长驻服务
- 未碰生产数据
