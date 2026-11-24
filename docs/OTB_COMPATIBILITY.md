# OpenTenBase 兼容性基线

scripts/verify_otb_compatibility.py 对 AIOps 使用的 PostgreSQL 兼容接口逐项执行只读探测。每个 SQL 探测独立回滚，使用 1.5 秒语句超时和 300 毫秒锁超时。脚本还会对 pgxc_node 注册的 CN、DN、GTM 地址进行 TCP 连通性检查。探测失败或节点地址缺失都会导致整体验收失败。

当前已验证的 OpenTenBase 实验版本为 OpenTenBase_v5.0，服务器返回 PostgreSQL 10.0 兼容标识。AIOps API 容器通过 psycopg2 使用 otb-node1:11003 成功建立连接，并读取到 pgxc_node、pg_stat_activity、pg_locks、pg_prepared_xacts 和 pg_stat_replication。

实验集群中存在一个长期 prepared transaction，GID 为 _$XC$21973:cn0001:T:2:1。它会导致部分涉及事务元数据的读取等待或超时。AIOps 不会自动提交或回滚它，兼容性报告必须把相关探测标为失败或部分成功。

从 API 容器使用临时普通登录角色直接连接 `lab` 的两个 DN 时，两个端点均返回 `no pg_hba.conf entry`。临时角色已删除。若改用直接 DN 连接做最小权限验证，需要由部署方为指定来源、数据库和角色配置认证规则，然后逐节点验证登录和本地统计读取权限。

在 `lab` 库的隔离复制表上，使用 `SET LOCAL ROLE` 切换到临时普通表所有者后，成功取得 `SHARE UPDATE EXCLUSIVE` 锁，`ANALYZE` 无警告返回。测试事务已回滚，临时角色和表随之清理。本次单独验证了 CN 上的表锁和命令权限，独立登录和执行后的双 DN 统计复核仍需验收。

后续在独立的 `lab` 测试表上以普通表所有者身份提交 `ANALYZE`。通过现有管理连接读取统计，确认 DN1 和 DN2 的 `last_analyze` 均更新。测试表和角色已删除。独立低权限连接读取双 DN 统计仍待验收。

独立账号复测使用 `lab` 库中的临时普通登录角色作为隔离复制表的所有者。通过 FastAPI 测试客户端创建和审批提案，执行结果中的 `database_session_user` 与临时角色一致，巡检账号确认两个 DN 的 `last_analyze` 均更新，重复审批返回 HTTP 400。本次使用模拟模型响应和现有 CN 认证规则，测试表、角色和审计记录均已清理。

## 验收顺序

1. 运行 python scripts/verify_otb_compatibility.py。
2. 确认连接身份、节点、会话、锁和复制探测结果。
3. 对失败探测记录 SQL 错误和数据库状态。
4. 分别验收全库采集和目标表采集。目标表提案要求逐 DN 统计完整，执行后复查每个参与节点的 `last_analyze`。

### 批量统计超时后的修复验收

在真实 OpenTenBase 上用隔离复制表验收。全库巡检保持 `partial`，单表补充采集取得两个 DN 的统计，并生成 `statistics_source=fallback` 的统计过时发现。通过测试客户端调用实际提案和审批端点后，请求状态为 `executed`，两个 DN 的 `last_analyze` 均更新。重复审批返回 HTTP 400。验收使用模拟模型响应，测试表和审计记录已清理。

逐人令牌复测使用显式节点组创建隔离复制表，批量插入 1800 行并断开写入会话后等待统计刷新。目标表巡检读到两个 DN 各有 1800 次修改，随后通过 FastAPI 测试客户端创建提案并批准执行。数据库记录了令牌绑定的操作者，两个 DN 的 `last_analyze` 均更新，重复审批返回 HTTP 400。模型响应为模拟数据，测试表、审计记录及修复请求均已清理。

兼容性通过只说明采集接口和字段可用，不代表已经验证了采集开销、跨 CN 锁图完整性或修复操作安全性。

## 2026-11-24 实测结果

### 同集群 `lab` 数据库全量采集

从 API 容器将探测目标设为 `lab` 后，9 项 SQL 探测均通过，四个注册节点均可达，两个 DN 共返回 4 张表的统计。随后在独立测试进程中把每个 DN 的采集上限设为 1，两个 DN 均报告 `CollectionLimit`，全量巡检标记为 `partial`，同时 `public.memories` 的补采取得了双 DN 统计。该验收只读取数据库，部署默认目标仍是 `postgres`，其全量统计恢复仍待复验。

通过 API 容器内的巡检引擎执行无目标表的完整巡检并回读审计库。审计 ID 为 `e66f700c-40ca-4436-87f9-799802575b83`，数据库确认为 `lab`，采集状态为 `success`，共记录 4 张表的 DN 统计。模型 HTTP 状态单独记录为 `403`。

### `postgres` 数据库故障与目标表验收

隔离拓扑复测时，临时 DN 曾在日志中报告已开始监听，随后 CN 连接被拒绝。Docker Linux 内核日志记录了 `otb-node1` 所属 cgroup 内两次全局 OOM，均杀死了 `postgres` 进程。容器未设置独立内存上限，检查时 Docker Linux 环境的 2 GiB swap 已接近耗尽。内核日志使用宿主 PID，尚未将两次事件逐一映射到临时 DN 的容器 PID。下次隔离恢复验收需为拓扑预留独立内存预算，并在启动 CN 前持续检查 DN 连通性。

构建 `b612d77cb` 对应的 `pg_clean--1.0.sql` 明确将诊断、事务提交与回滚、记录清理等函数授予 `PUBLIC`。安装验收应检查普通角色的有效执行权限，并限制恢复入口的授权。已有后台清理器启用的实例还需单独验证注册扩展后是否会立即处理存量预备事务。当前仅核对了安装脚本，尚未实测扩展权限或安装时的后台行为。

同版本源码显示，`pg_clean` 通过各节点上的 `public.pgxc_get_2pc_file`、`public.pgxc_get_record_list` 等 SQL 辅助函数读取事务记录。已从 `lab` 的 CN 和两个 DN 分别查询 `pg_proc`，均未找到诊断入口或这些辅助函数。动态库加载已通过，运行集群级诊断还需要验证各参与节点上的扩展 SQL 定义。

对应构建 `b612d77cb` 的 `contrib/pg_clean/pg_clean.c` 中，`pg_clean_check_txn` 仅允许在 CN 调用，以 `execute = false` 进入状态收集流程，并枚举数据库及 CN、DN 上的事务。诊断结果包含 GID、数据库、全局状态和各节点状态。调用范围覆盖集群，连接到 `lab` 并不能将诊断限制到该库。扩展的恢复入口由独立的 `pg_clean_execute*` 函数提供。当前实测只覆盖动态库加载，尚未调用这些 SQL 函数。

跨节点加载复测确认两个容器拥有独立的数据卷。将同一构建产物临时放在两个容器的相同路径并核对 SHA-256 后，通过 CN 的 `lab` 只读会话执行 `LOAD` 成功，随后回滚并关闭会话。DN2 上的临时副本已清理。扩展安装和两阶段事务恢复仍待验证。

使用同版本编译的 `pg_clean.so`，直连 DN1 的 `lab` 数据库，在只读事务中执行 `LOAD` 成功，随后回滚并关闭会话。经 CN 执行同一命令时返回 `58P01`。本地构建对应的 `src/backend/tcop/utility.c` 显示 CN 会将 `LOAD` 下发到 DN，本次临时动态库只编译在 DN1 所在容器。此测试验证了 DN1 的动态加载，跨节点加载及恢复行为仍待验证。

当前 CN 的 `version()`、安装目录的 `pg_config` 和本地 OpenTenBase 源码都指向构建提交 `b612d77cb`。将该版本的 `contrib/pg_clean` 复制到临时目录后，使用安装目录的 `pg_config` 和 `USE_PGXS=1` 成功构建 `pg_clean.so`。构建产物未安装到运行实例，加载和事务恢复仍待隔离环境验收。

OpenTenBase v5.0 的后台清理器在查询待恢复事务前检查 `public.pg_clean_check_txn`。当前安装的 `pg_available_extensions` 中没有 `pg_clean`，CN 日志中多次出现 `create extension pg_clean please`。因此清理启动器虽已启用，当前部署缺少它所需的扩展。后续应先核对扩展与当前服务端构建的兼容性，再在隔离环境验证其只读诊断和恢复行为。 [OpenTenBase v5.0 后台清理源码](https://github.com/OpenTenBase/OpenTenBase/blob/v5.0/src/backend/postmaster/clean2pc.c)

安装包中的官方 `pgxc_clean` 提供 `-N` 只读收集模式。使用 `-N -s` 连接当前 CN 时，连接成功，但工具读取到 GTM 的 `node_type=G` 后以 `Invalid catalog data (node_type)` 退出，未能给出事务恢复判定。当前 CN 的 `enable_clean_2pc_launcher` 为 `on`，目标事务仍出现在 `pg_prepared_xacts`。

已逐节点只读核对该 GID 的 `pg_2pc` 文件。CN、DN1、DN2 的参与节点列表和 `global_prepare_timestamp` 一致。CN 文件另有 `global_commit_timestamp=308991314092`，两个 DN 文件均缺少该字段。这为核对 OpenTenBase 的两阶段提交恢复路径提供了持久化证据。事务仍待恢复。

CN 历史日志将 GID `_$XC$21973:cn0001:T:2:1` 关联到 2026-11-22 的 `aiops_kb_probe` 测试建表。日志记录全局状态为 `TWO_PHASE_COMMITTING`，两个 DN 均处于 `TWO_PHASE_COMMIT_ERROR`，原始错误为 `can not commit transaction ... in xc_maintainence_mode`。当前 CN 会话通过 `to_regclass` 查不到该表，预备事务仍存在。上述证据确认了发起语句及当时的提交尝试，最终处置仍需核对协调器持久化决议和各参与节点的状态。

API 容器能够通过 psycopg2 连接 OpenTenBase_v5.0 的 CN，读取节点注册信息、会话、锁、prepared transaction 和复制视图。完整健康巡检生成了审计记录并回读到 5 条知识引用。

首次巡检发现 DN2 `172.28.50.12:11006` 拒绝连接。检查确认数据目录的 `postmaster.pid` 已过期后，备份该文件并以 `pg_ctl -Z datanode` 恢复 DN2。恢复后 CN、DN1、DN2 和 GTM 的 TCP 探测均通过。

恢复 DN2 后，真实集群上的隔离表已完成目标表巡检、创建提案、人工批准、执行 `ANALYZE` 和逐 DN 复查。两个 DN 的 `last_analyze` 均更新，测试表和测试记录已清理。目标表入口支持 `POST /api/audits/health?table=schema.table`，周期巡检可通过 `AIOPS_AUTO_AUDIT_TABLE` 指定目标。

全库巡检通过 `EXECUTE DIRECT ON` 读取各 DN 的统计视图。当前表统计、索引统计和两个 DN 的批量表统计均观测到 SQLSTATE `55P03`。协调节点的 `pgxc_class` 扫描也超时，`pg_namespace` 查询成功。目标表巡检通过 OID 读取统计函数，现场验收时避开了这类目录扫描。

协调节点的锁证据显示 XID `21973` 同时有已授予的排他事务锁和等待者。关联 GID 在两个 DN 上也有预备事务记录。事务归属方需核对应用与协调器记录后确定处置。处置后重新运行无目标健康巡检，逐项核对 `table_stats`、`index_usage` 和各 DN 统计查询的采集状态。全库统计验收以这些查询实测成功为准。

复测时，CN 和两个 DN 上直接扫描 `pg_class`、`pg_stat_user_tables` 和 `pg_stat_user_indexes` 均返回 `55P03`，`pg_namespace` 读取成功。分别在每个节点上使用独立会话观测 `pg_class` 扫描，超时前均捕获到未授予的 `transactionid ShareLock`。CN 等待本地 XID `21973`，DN1 等待 `11576`，DN2 等待 `11457`。各节点的 `pg_prepared_xacts` 将这些本地 XID 映射到同一 GID `_$XC$21973:cn0001:T:2:1`。

健康巡检采集到真实锁等待，并识别出与 XID `21973` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 `function_call` 字段的 422 错误。
### 数据节点目录分段复测

在当前实验集群上，通过 CN 对 DN1 和 DN2 执行相同的只读 `pg_class` 计数查询。查询限定普通表（`relkind = 'r'`），锁超时为 300 ms，语句超时为 2 秒。

| OID 范围 | DN1 | DN2 |
| --- | --- | --- |
| 16384–57354 | `55P03` | `55P03` |
| 57355–65535 | 3 张表 | 3 张表 |
| 65536–100000 | 0 张表 | 0 张表 |

这些区间用于定位本次实验的阻塞范围。全库统计验收仍要求各 DN 的批量查询通过。
