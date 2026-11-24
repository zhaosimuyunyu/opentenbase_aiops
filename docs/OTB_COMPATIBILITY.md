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

同一次巡检的节点连通性结果为：CN、DN1 和 GTM 可达，DN2 `172.28.50.12:11006` 拒绝连接。DN2 数据目录中的 `postmaster.pid` 记录的 PID 当前不存在，但尝试启动时 OpenTenBase 检测到 PID 冲突并拒绝启动。未删除 PID 文件或处理预备事务。

由于 DN2 不可达，跨节点建表探针返回 `InsufficientResources`，提示连接 DN2 失败。最近一次只读 SQL 兼容性验证中，8 项探针 7 项通过，表统计因锁超时失败，索引统计通过。因此当前状态是“CN 协议连接已验证，完整集群可用性不通过”，不能声称修复执行链路已端到端验收。

隔离 ANALYZE 测试没有创建持久对象。批准执行端点也尚未实测，API 当前没有配置 `AIOPS_APPROVAL_TOKEN`。

健康巡检采集到真实锁等待，并识别出与 XID `21973` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 `function_call` 字段的 422 错误。
