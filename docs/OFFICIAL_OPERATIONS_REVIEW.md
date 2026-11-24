# OpenTenBase 官方运维能力核对

核对日期：2026-11-24。核对对象为 OpenTenBase 官方 GitHub 仓库 `OpenTenBase/OpenTenBase` 和 `OpenTenBase/docs`。代码仓库参考固定提交 `b2b129b35b58855ea0017650ab2abce192a4d93c`，文档仓库参考固定提交 `4eaeba90188926ddf4da23b74775cdf150ffdfe8`。

## 核对结论

官方提供了数据库内的监控视图、分布式死锁诊断扩展、节点存活检测工具、SQL 行为审计能力，以及基于 Prometheus、Grafana 和 `postgres_exporter` 的监控部署指南。检查到的官方 AIOPS GitHub 仓库当时没有提交内容，未发现可直接调用的统一 AIOps 审计 REST API。

这些能力解决不同问题，不能互相替代。

| 官方能力 | 作用 | 集成判断 |
|---|---|---|
| `pg_stat_activity`、`pg_locks`、`pg_stat_replication` 等系统视图 | 查询当前会话、锁和复制状态 | 可由巡检采集器通过只读 SQL 查询。它们是数据库内置观测接口，不是独立的审计服务 |
| `pg_unlock` 扩展 | 查询跨 CN 事务依赖、检测分布式死锁，并提供解锁/终止事务函数 | 应先探测扩展是否已安装以及版本是否匹配。`pg_unlock_check_dependency()` 和 `pg_unlock_check_deadlock()` 可用于诊断；`pg_unlock_execute()` 与 `pg_unlock_killbypid()` 会终止事务或会话，属于写操作，必须从只读自动工具中隔离 |
| `pgxc_monitor` 命令 | 检查 GTM、CN、DN 节点是否可连接/运行 | 可作为节点存活探针补充 SQL 指标；不能提供锁等待、容量或历史趋势数据 |
| OpenTenBase SQL 审计子系统 | 回归用例展示 `AUDIT ALL`、按用户/对象设置审计，以及查询审计配置视图 | 属于数据库行为审计和合规日志，不是健康巡检或根因诊断接口。官方仓库中这次找到的是回归测试，不是管理员部署手册；启用配置、日志位置和性能开销需按目标版本核实 |
| 官方 Prometheus/Grafana/`postgres_exporter` 指南 | 周期采集指标并提供时序图表 | 适合长期趋势和告警。数据库 exporter 账户使用 `pg_monitor` 等权限时应按实际 OpenTenBase 版本验证最小权限，避免照搬示例中的弱口令 |

## 权限与风险

固定提交中的 `contrib/pg_unlock/pg_unlock--1.0.sql` 对多个函数执行 `GRANT ALL ... TO PUBLIC`，包括 `pg_unlock_execute()`、`pg_unlock_killbypid()`。安装该扩展后，必须检查目标版本实际函数 ACL 和部署策略。不能把该扩展函数原样注册为 Agent tool，也不能假设创建专用只读数据库用户就足以限制它们。

本项目当前锁采集器直接读取 `pg_locks` 并连接 `pg_stat_activity`，它没有调用 `pg_unlock`。巡检 SQL 以只读事务执行并设置 statement/lock timeout，但只读巡检 API 仍属于本项目自建逻辑。

## 入库与来源核验

`scripts/import_operations_docs.py` 已把此前遗漏的官方 `monitoring.sgml`、`pgxcmonitor.sgml`，以及 `pg_unlock` 扩展安装 SQL 加入待导入清单。清单还包含官方 `pg_unlock` 和 Prometheus 监控指南中英文版本。脚本按来源 URL、固定提交号和 SHA-256 内容摘要核对资料，并在写入后检查片段内容、向量维度及来源元数据。扩展 SQL 使用 `official_source` 分类，知识检索工具已允许 AI 显式搜索该分类。

Docker Engine 恢复后，三份新增资料已写入 pgvector 并逐篇校验，共 281 个片段。知识库实测总计 67 份资料、3,501 个片段，12 项检索回归全部通过。OpenTenBase CN 的 11003 端口拒绝连接，巡检仅验证了采集失败分支，尚无扩展兼容性或性能实测结果。

代码仓库中的审计回归测试展示了审计配置语法和配置视图，但测试包含创建超级用户、删除数据库等破坏性步骤，不适合直接导入为生产操作指南。因此没有把测试脚本包装成官方操作手册，也没有将数据库行为审计误称为健康巡检 API。

## 官方来源

- OpenTenBase 代码仓库 [contrib/pg_unlock/pg_unlock--1.0.sql](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/contrib/pg_unlock/pg_unlock--1.0.sql)
- OpenTenBase 代码仓库 [contrib/pgxc_monitor](https://github.com/OpenTenBase/OpenTenBase/tree/b2b129b35b58855ea0017650ab2abce192a4d93c/contrib/pgxc_monitor)
- OpenTenBase 代码仓库 [pgxc_monitor 手册](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/doc/src/sgml/pgxcmonitor.sgml)
- OpenTenBase 代码仓库 [SQL 审计回归用例](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/src/test/regress/sql/audit.sql)
- OpenTenBase 文档 [pg_unlock 使用说明](https://github.com/OpenTenBase/docs/blob/4eaeba90188926ddf4da23b74775cdf150ffdfe8/docs/guide/11-pg_unlock.md)
- OpenTenBase 文档 [监控部署指南](https://github.com/OpenTenBase/docs/blob/4eaeba90188926ddf4da23b74775cdf150ffdfe8/docs/guide/13-opentenbase_monitoring.md)
- OpenTenBase GitHub 组织 [AIOPS 仓库](https://github.com/OpenTenBase/AIOPS)
