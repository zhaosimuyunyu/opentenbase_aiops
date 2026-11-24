# OpenTenBase 兼容性基线

scripts/verify_otb_compatibility.py 对 AIOps 使用的 PostgreSQL 兼容接口逐项执行只读探测。每个 SQL 探测独立回滚，使用 1.5 秒语句超时和 300 毫秒锁超时。脚本还会对 pgxc_node 注册的 CN、DN、GTM 地址进行 TCP 连通性检查。探测失败或节点地址缺失都会导致整体验收失败。

当前已验证的 OpenTenBase 实验版本为 OpenTenBase_v5.0，服务器返回 PostgreSQL 10.0 兼容标识。AIOps API 容器通过 psycopg2 使用 otb-node1:11003 成功建立连接，并读取到 pgxc_node、pg_stat_activity、pg_locks、pg_prepared_xacts 和 pg_stat_replication。

实验集群中存在一个长期 prepared transaction，GID 为 _$XC$21973:cn0001:T:2:1。它会导致部分涉及事务元数据的读取等待或超时。AIOps 不会自动提交或回滚它，兼容性报告必须把相关探测标为失败或部分成功。

## 验收顺序

1. 运行 python scripts/verify_otb_compatibility.py。
2. 确认连接身份、节点、会话、锁和复制探测结果。
3. 对失败探测记录 SQL 错误和数据库状态。
4. 分别验收全库采集和目标表采集。目标表提案要求逐 DN 统计完整，执行后复查每个参与节点的 `last_analyze`。

兼容性通过只说明采集接口和字段可用，不代表已经验证了采集开销、跨 CN 锁图完整性或修复操作安全性。

## 2026-11-24 实测结果

API 容器能够通过 psycopg2 连接 OpenTenBase_v5.0 的 CN，读取节点注册信息、会话、锁、prepared transaction 和复制视图。完整健康巡检生成了审计记录并回读到 5 条知识引用。

首次巡检发现 DN2 `172.28.50.12:11006` 拒绝连接。检查确认数据目录的 `postmaster.pid` 已过期后，备份该文件并以 `pg_ctl -Z datanode` 恢复 DN2。恢复后 CN、DN1、DN2 和 GTM 的 TCP 探测均通过。

恢复 DN2 后，真实集群上的隔离表已完成目标表巡检、创建提案、人工批准、执行 `ANALYZE` 和逐 DN 复查。两个 DN 的 `last_analyze` 均更新，测试表和测试记录已清理。目标表入口支持 `POST /api/audits/health?table=schema.table`，周期巡检可通过 `AIOPS_AUTO_AUDIT_TABLE` 指定目标。

全库巡检通过 `EXECUTE DIRECT ON` 读取各 DN 的统计视图。当前表统计、索引统计和两个 DN 的批量表统计均观测到 SQLSTATE `55P03`。协调节点的 `pgxc_class` 扫描也超时，`pg_namespace` 查询成功。目标表巡检通过 OID 读取统计函数，现场验收时避开了这类目录扫描。

协调节点的锁证据显示 XID `21973` 同时有已授予的排他事务锁和等待者。关联 GID 在两个 DN 上也有预备事务记录。事务归属方需核对应用与协调器记录后确定处置。处置后重新运行无目标健康巡检，逐项核对 `table_stats`、`index_usage` 和各 DN 统计查询的采集状态。全库统计验收以这些查询实测成功为准。

健康巡检采集到真实锁等待，并识别出与 XID `21973` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 `function_call` 字段的 422 错误。
