# OpenTenBase 兼容性基线

scripts/verify_otb_compatibility.py 对 AIOps 使用的 PostgreSQL 兼容接口逐项执行只读探测。每个探测独立回滚，使用 1.5 秒语句超时和 300 毫秒锁超时。探测失败会单独记录，不能被报告为整体成功。

当前已验证的 OpenTenBase 实验版本为 OpenTenBase_v5.0，服务器返回 PostgreSQL 10.0 兼容标识。AIOps API 容器通过 psycopg2 使用 otb-node1:11003 成功建立连接，并读取到 pgxc_node、pg_stat_activity、pg_locks、pg_prepared_xacts 和 pg_stat_replication。

实验集群中存在一个长期 prepared transaction，GID 为 _$XC$21973:cn0001:T:2:1。它会导致部分涉及事务元数据的读取等待或超时。AIOps 不会自动提交或回滚它，兼容性报告必须把相关探测标为失败或部分成功。

## 验收顺序

1. 运行 python scripts/verify_otb_compatibility.py。
2. 确认连接身份、节点、会话、锁和复制探测结果。
3. 对失败探测记录 SQL 错误和数据库状态。
4. 只有兼容性基线通过后，才启用审计建议和人工采纳执行流程。

兼容性通过只说明采集接口和字段可用，不代表已经验证了采集开销、跨 CN 锁图完整性或修复操作安全性。

## 当前实测结果

2026-11-24 在 OpenTenBase_v5.0 实验集群执行了 8 项探测。7 项通过，1 项失败。失败项是表统计查询，返回 \`LockNotAvailable\`，原因是现有 prepared transaction \`21973\` 的事务锁等待。连接本身、节点、会话、锁、prepared transaction、复制和索引统计均可通过 \`psycopg2\` 读取。

健康巡检随后成功采集到真实锁等待，并识别出与 XID \`21973\` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 \`function_call\` 字段的 422 错误。
