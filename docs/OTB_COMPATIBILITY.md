# OpenTenBase 兼容性基线

scripts/verify_otb_compatibility.py 对 AIOps 使用的 PostgreSQL 兼容接口逐项执行只读探测。每个 SQL 探测独立回滚，使用 1.5 秒语句超时和 300 毫秒锁超时。脚本还会对 pgxc_node 注册的 CN、DN、GTM 地址进行 TCP 连通性检查。探测失败或节点地址缺失都会导致整体验收失败。

当前已验证的 OpenTenBase 实验版本为 OpenTenBase_v5.0，服务器返回 PostgreSQL 10.0 兼容标识。AIOps API 容器通过 psycopg2 使用 otb-node1:11003 成功建立连接，并读取到 pgxc_node、pg_stat_activity、pg_locks、pg_prepared_xacts 和 pg_stat_replication。

实验集群中存在一个长期 prepared transaction，GID 为 _$XC$21973:cn0001:T:2:1。它会导致部分涉及事务元数据的读取等待或超时。AIOps 不会自动提交或回滚它，兼容性报告必须把相关探测标为失败或部分成功。

## 验收顺序

1. 运行 python scripts/verify_otb_compatibility.py。
2. 确认连接身份、节点、会话、锁和复制探测结果。
3. 对失败探测记录 SQL 错误和数据库状态。
4. 只有兼容性基线通过后，才启用审计建议和人工采纳执行流程。

兼容性通过只说明采集接口和字段可用，不代表已经验证了采集开销、跨 CN 锁图完整性或修复操作安全性。

## 2026-11-24 实测结果

API 容器能够通过 psycopg2 连接 OpenTenBase_v5.0 的 CN，读取节点注册信息、会话、锁、prepared transaction 和复制视图。完整健康巡检生成了审计记录并回读到 5 条知识引用。

首次巡检发现 DN2 `172.28.50.12:11006` 拒绝连接。检查确认数据目录的 `postmaster.pid` 已过期后，备份该文件并以 `pg_ctl -Z datanode` 恢复 DN2。恢复后 CN、DN1、DN2 和 GTM 的 TCP 探测均通过。

恢复 DN2 后，隔离建表验证仍因现存 prepared transaction `21973` 造成的锁超时而未完成。最近一次只读 SQL 兼容性验证中，8 项探针 7 项通过，表统计因锁超时失败，索引统计通过。节点网络可达，但完整 SQL 兼容性尚未通过。

巡检现在通过 `EXECUTE DIRECT ON` 分别读取各 DN 的 `pg_stat_user_tables` 并聚合统计。当前两台 DN 的统计查询均因 prepared transaction 锁超时而失败，因此审计不会生成 ANALYZE 提案。批准执行端点也尚未实测，API 当前没有配置 `AIOPS_APPROVAL_TOKEN`。

健康巡检采集到真实锁等待，并识别出与 XID `21973` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 `function_call` 字段的 422 错误。
