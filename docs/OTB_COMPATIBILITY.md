# OpenTenBase 兼容性基线

健康巡检会同时探测 `pg_clean_check_txn(integer)` 和官方内部记录读取函数 `pgxc_get_record_list()`。当前实验集群两者均未注册，因此当锁等待与 prepared transaction 关联时，审计会明确生成低风险的 `official_2pc_record_diagnostics_unavailable` 发现。该发现表示官方诊断覆盖缺失，不表示 AIOps 可以安全替代官方 2PC 恢复流程。

### 分布式直连采集的超时与现场复测

`DistributedCollector` 对每个直连 CN/DN 的只读检查统一设置事务级 `statement_timeout=2500ms` 和 `lock_timeout=750ms`，失败会回滚该检查并将异常类型及 SQLSTATE 放入对应节点的 `errors`。2026-11-25 在真实集群上对两个 DN 执行 `locks` 检查均成功。执行 `table_stats` 时两个 DN 都在目录锁等待中以 SQLSTATE `55P03` 结束，节点状态为 `partial`，且接口在约 2 秒内返回。这与普通的“节点成功/失败”汇总不同，保留了每节点每检查的部分结果，便于定位 prepared transaction 造成的目录扫描阻塞。

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

### 真实模型联合验收

在独立测试库使用有两个 DN 的复制测试表。准备足量写入并等待统计刷新，使目标表达到 `stale_table_statistics` 阈值。巡检账号应能读取逐 DN 统计，修复账号应具有目标表的维护权限。配置可调用的 OpenAI 兼容端点后，用 `docker compose up -d aiops-api` 应用环境变量。

1. 调用 `POST /api/audits/health?table=schema.table`，记录审计 ID。用 `GET /api/audits/{audit_id}` 确认目标表发现、各 DN 证据、`ai_analysis.structured.analysis_source=model` 和官方知识引用。HTTP 403、规则回退或空引用均不满足本项验收。
2. 调用 `POST /api/audits/{audit_id}/repair-requests`，用该发现的零基索引作为 `finding_index`，填写 `reason`。确认提案为 `pending` 且引用原始巡检结果。当前 `ANALYZE` 提案由统计规则生成，模型诊断随提案保存。
3. 由具名审批人审批，使用审批页或 `POST /api/repairs/{request_id}/approve`。在 `GET /api/repairs` 回读请求，确认审批人、`executed` 状态、各 DN 前后 OID 一致，以及每个目标 DN 的 `last_analyze` 均推进。保留审计 ID 和请求 ID 作为验收记录。

2026-11-25，网关恢复后在真实 `lab` 集群完成联合验收。第一次运行完成了知识检索，但模型在生成最终报告时超时。第二次仅对验收进程设置 `DEEPSEEK_TIMEOUT_SECONDS=150`，真实模型成功生成结构化诊断并通过检索工具取得 5 条固定版本官方引用。通过 API 路由函数提交测试审批，由独立普通账号执行 `ANALYZE`。持久化结果为 `executed`，审批身份为测试配置中的 `local-operator`，两个 DN 的表 OID 均保持一致，`last_analyze` 均从空值更新。测试表和账号已清理，保留审计 `fbd32849-4d8b-4bb4-935e-e0b7189a01e4` 和修复请求 `6967d05a-deb0-4b86-b9be-35d13cd46d2f`。本次使用现有非流式接口。

### 批量统计超时后的修复验收

2026-11-25，在真实 `lab` 集群验证逐 DN 阈值和三道审批。复制测试表在两个 DN 上各有 1800 次修改，执行前记录的 `stale_nodes` 同时包含两个 DN。真实模型调用知识检索后生成诊断，程序校验和复核 Agent 通过，测试脚本提交具名审批后由独立普通账号执行 `ANALYZE`。双方表 OID 保持一致，`last_analyze` 均更新，修复状态为 `executed`。测试表和角色已清理，保留审计 `3f750b93-cf9a-443a-8c9e-dbe6c486125c` 和修复请求 `88e0006e-5609-4bc4-aaed-47b7d25afc07`。

启用独立修复账号要求后，在真实 `lab` 库重跑目标表巡检、提案和审批。临时普通登录角色拥有复制测试表，审批执行结果的数据库会话身份与该角色一致。只读复查连接确认 `dn0001` 和 `dn0002` 的表 OID 均与执行前一致，两个节点的 `last_analyze` 均推进，请求状态为 `executed`。审计 API 回读到 3 条知识引用。该次运行的模型端点返回 HTTP 403，诊断使用规则回退。测试表、角色、修复请求和审计记录均已清理。

在真实 OpenTenBase 上用隔离复制表验收。全库巡检保持 `partial`，单表补充采集取得两个 DN 的统计，并生成 `statistics_source=fallback` 的统计过时发现。通过测试客户端调用实际提案和审批端点后，请求状态为 `executed`，两个 DN 的 `last_analyze` 均更新。重复审批返回 HTTP 400。验收使用模拟模型响应，测试表和审计记录已清理。

逐人令牌复测使用显式节点组创建隔离复制表，批量插入 1800 行并断开写入会话后等待统计刷新。目标表巡检读到两个 DN 各有 1800 次修改，随后通过 FastAPI 测试客户端创建提案并批准执行。数据库记录了令牌绑定的操作者，两个 DN 的 `last_analyze` 均更新，重复审批返回 HTTP 400。模型响应为模拟数据，测试表、审计记录及修复请求均已清理。

兼容性通过只说明采集接口和字段可用，不代表已经验证了采集开销、跨 CN 锁图完整性或修复操作安全性。

## 2026-11-24 实测结果

### 同集群 `lab` 数据库全量采集

从 API 容器将探测目标设为 `lab` 后，9 项 SQL 探测均通过，四个注册节点均可达，两个 DN 共返回 4 张表的统计。随后在独立测试进程中把每个 DN 的采集上限设为 1，两个 DN 均报告 `CollectionLimit`，全量巡检标记为 `partial`，同时 `public.memories` 的补采取得了双 DN 统计。该验收只读取数据库，部署默认目标仍是 `postgres`，其全量统计恢复仍待复验。

通过 API 容器内的巡检引擎执行无目标表的完整巡检并回读审计库。审计 ID 为 `e66f700c-40ca-4436-87f9-799802575b83`，数据库确认为 `lab`，采集状态为 `success`，共记录 4 张表的 DN 统计。模型 HTTP 状态单独记录为 `403`。

### `postgres` 数据库故障与目标表验收

同版本隔离拓扑上，在创建复制表并写入测试行的事务内，通过会话级 `SET xc_maintenance_mode=on` 使隐式两阶段提交在 `TWO_PHASE_COMMIT_END` 中断。重启隔离拓扑后，官方 `pg_clean_check_txn(10)` 所见状态为全局 `TXN_STATUS_COMMITTED`、CN `PREPARED`、DN `COMMITTED`。随后调用 `pg_clean_execute(10)` 返回 `COMMIT / success`。分别回查 CN 和 DN 的 `pg_prepared_xacts` 均为空，经 CN 及直达 DN 的查询均返回测试行 `42`。测试表及节点组已清理，隔离实例已停止。

上述提交验收覆盖至少一个参与节点已提交的故障状态。现场故障中两个 DN 的提交均报错，协调器另有持久化提交时间戳，仍需验证所有节点保持预备时官方工具如何使用该时间戳。隔离实验期间未更改现场事务。

核对同构建的 `contrib/pg_clean/pg_clean.c` 后确认，官方工具在排除未知、冲突状态并确认至少一个节点处于预备状态后，即使未观测到已提交节点，也会将具有有效全局提交时间戳的事务判为 `TXN_STATUS_COMMITTED`。这是源码层面的核验。现场恢复前仍需确认工具实际读到的状态、扩展权限和后台清理器行为。

### 只读采集耗时基线

隔离对照实验在同版本 CN 和 DN 上创建显式预备事务，停机后仅为隔离 CN 的测试记录补入合成提交时间戳。重启后，`pg_clean_check_txn(10)` 报告全局及两个参与节点均为 `TXN_STATUS_PREPARED`。源码在显式事务已过第一阶段且参与节点均为 PREPARED 时提前返回该状态。实验已还原隔离文件并回滚，回查 CN 和 DN 均无残留预备事务，测试表和节点组已清理。现场为隐式事务，仍需独立验证其补提交路径。

从 API 容器直接调用 `ReadonlyHealthCollector.collect`，连接真实两 DN 集群的 `lab`。全库和 `public.memories` 两组各串行运行 20 次，均为 20/20 成功。耗时包括建立连接和采集，范围止于采集器返回。

| 采集范围 | 中位数 | P95（最近秩） | 最大值 |
| --- | ---: | ---: | ---: |
| 全库 | 84.2 ms | 116.1 ms | 117.4 ms |
| `public.memories` | 71.7 ms | 102.2 ms | 108.9 ms |

此基线来自小规模实验库。生产性能验收还需在代表性并发负载下测量采集对业务延迟和数据库资源的影响。

在隔离 CN、DN 和 GTM 上，对复制表写入后创建显式预备事务。官方诊断报告 CN 和 DN 均为 `TXN_STATUS_PREPARED`，全局状态为 `TXN_STATUS_ABORTED`。恢复函数在此构建中要求事务至少达到 10 秒，达到阈值后执行 `pg_clean_execute(10)` 返回 `ABORT / success`。分别在 CN 和 DN 查询 `pg_prepared_xacts`，测试 GID 均已消失，测试表的行数为 0。测试表和节点组已清理，隔离进程已停止。本次验证覆盖回滚路径，现场带持久化提交时间戳的事务需要单独验证提交恢复路径。

带事务的隔离验收使用显式 `PREPARE TRANSACTION` 创建测试 GID。立即调用 `pg_clean_check_txn(120)` 返回空结果。等待 5 秒后改用 `pg_clean_check_txn(3)`，诊断返回该 GID 和 `TXN_STATUS_COMMITTED`，同时报告缺少全局追踪 ID。诊断后，该 GID 仍在 `pg_prepared_xacts` 中，随后使用 `ROLLBACK PREPARED` 清理测试事务。此结果验证了诊断能够发现达到检查年龄的预备事务。恢复验收须逐节点确认实际事务状态。这笔测试事务也未复现现场的跨节点提交故障。

隔离拓扑中已注册并调用官方 `pg_clean_check_txn` 及诊断所需的辅助函数，后台清理器保持关闭。诊断会按 `pgxc_node` 连接 CN 自身，因此临时 CN 的目录端口需从默认 `5432` 改为实际监听的 `19147`，并启用本地 TCP 监听。修正后，`pg_clean_check_txn(120)` 在无预备事务的隔离拓扑上成功返回空结果。临时进程已停止，带预备事务的诊断和恢复仍待验证。

同版本隔离 GTM、CN 和 DN 已通过 `pg_clean.so` 加载验收。临时 CN 和 DN 使用 `fn_shared_buffers=12800`、`shared_buffers=32MB`、`max_connections=20`、`max_wal_senders=2`、`max_prepared_transactions=32` 和 `pg_workfile_max_entries=1024`，共享内存申请降至约 771 MiB 和 637 MiB。DN 在 CN 启动前后均通过连接检查。随后在临时 DN 注册 CN 节点，解决了处理 `SET global_session` 时的节点找不到错误。从临时 CN 执行 `LOAD` 成功，三个临时进程均已停止。此验收尚未注册扩展函数或执行事务恢复。

隔离拓扑复测时，临时 DN 曾在日志中报告已开始监听，随后 CN 连接被拒绝。Docker Linux 内核日志记录了 `otb-node1` 所属 cgroup 内两次全局 OOM，均杀死了 `postgres` 进程。容器未设置独立内存上限，检查时 Docker Linux 环境的 2 GiB swap 已接近耗尽。内核日志使用宿主 PID，尚未将两次事件逐一映射到临时 DN 的容器 PID。下次隔离恢复验收需为拓扑预留独立内存预算，并在启动 CN 前持续检查 DN 连通性。

构建 `b612d77cb` 对应的 `pg_clean--1.0.sql` 明确将诊断、事务提交与回滚、记录清理等函数授予 `PUBLIC`。安装验收应检查普通角色的有效执行权限，并限制恢复入口的授权。已有后台清理器启用的实例还需单独验证注册扩展后是否会立即处理存量预备事务。当前仅核对了安装脚本，尚未实测扩展权限或安装时的后台行为。

后续在同版本隔离 CN 实测，普通角色对注册的 `public.pg_clean_execute(integer)` 默认具有 `EXECUTE` 权限。事务内撤销 `PUBLIC` 的执行权限后，`has_function_privilege` 从真变为假，最后回滚测试事务。此测试只验证入口权限。官方 `pg_clean_execute` 按事务年龄扫描，`pg_clean_execute_on_node` 按节点与异常时间处理。两者的签名都没有 GID 参数，外层 `WHERE gid = ...` 只能过滤返回行。按节点和 GID 的提交与回滚辅助函数需要调用方指定决议，不能用它们替代官方全局状态判定。

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

### 2026-11-26 分布式统计采集复测

分布式拓扑中，健康巡检不再从 CN 执行全量表统计、索引统计和存储目录扫描，改为通过 `EXECUTE DIRECT ON` 在每个 DN 独立读取，并保留 DN 身份和逐节点错误。单节点或未发现 DN 时仍使用原 CN 查询。性能指标 API 和表统计页采用相同的 DN 采集方式，表统计结果包含表大小、索引大小、总大小和节点名称。

在当前 OpenTenBase v5.0 `postgres` 集群实测，健康巡检采集状态为 `success`，采集错误为空。结果包含 27 个按表汇总的统计项、76 条索引统计和 52 条 DN 存储记录。`/api/performance/metrics` 返回 `success`，包含 54 条表节点统计和 76 条索引统计，覆盖 `dn0001`、`dn0002`，锁记录共 38 条，采集错误为零。单项 DN 查询在该实验集群中约 5–20 ms，不能视为生产负载性能基线。

GXID `21973` 的 prepared transaction 和关联锁等待仍被报告为高风险，没有执行提交或回滚。官方 `pg_clean` 扩展在当前集群仍未安装，因此官方 2PC 状态诊断分支未被现场执行。

### 2026-11-26 SSE 场景验收与 readiness

`backend/tools/simulate_slow_query.py` 在 CN 会话中执行 15 秒 `pg_sleep`，通过慢日志记录捕获 `aiops-course-slow-query-demo`、PID、SQL 和约 15 秒耗时。SSE 返回完整审计结果，AI 使用真实模型分析，慢查询进入 `long_running_queries` 发现，模拟会话自然结束。审计 ID 为 `9f525178-4f01-4325-b0ab-a66d79bcca9f`。

`backend/tools/simulate_lock_wait.py` 在 `dn0001` 创建 advisory-lock blocker 和 waiter。直连 DN 查询确认 waiter 被 blocker PID 阻塞，随后 SSE 巡检生成 `data_node_lock_waits` 发现并捕获 blocker 的 application name。审计 ID 为 `5d363187-9616-4a70-aaeb-02e6f26140e8`，模拟结束后两个连接均已从 `pg_stat_activity` 消失；未执行修复。

API `/health` 现在同时检查 OpenTenBase 和用于审计/会话持久化的 metadata PostgreSQL，依赖均连接时返回 HTTP 200 和 `ready`，任一依赖失败时返回 HTTP 503 和 `not_ready`。当前容器实测两项依赖均连接，API、前端和知识库容器健康。

只读审计新记录显式保存为 `completed`。历史只读审计中遗留的默认 `pending` 状态会在审计列表和详情 API 中规范化为 `completed`，repair request 的审批状态不变。通过真实 SSE 巡检及审计详情回读验证了新旧状态。

这些场景验证功能闭环和故障发现，不构成生产并发负载下的容量或开销验收。独立修复账号未配置，本轮没有执行数据库修复。

### 2026-11-26 采集耗时基线

健康采集器记录 `collection_duration_ms`，范围包括 CN 检查、各 DN 直采、慢日志读取和节点连通探测，不包括 AI 分析及审计持久化。该值写入健康审计 evidence，并通过 Prometheus gauge `aiops_health_audit_latest_collection_duration_ms` 暴露。

从 API 容器对当前空闲 `postgres` 实验集群串行采集 10 次，10/10 为 `success` 且无采集错误。耗时中位数为 191.18 ms，最近秩 P95 为 356.29 ms，最大值为 356.29 ms。一次后续 SSE 巡检测得 212.97 ms，审计详情和 Prometheus gauge 均回读到相同数值。该基线不包含并发业务负载，不能作为生产容量或业务影响验收。

另以 3 个并发 worker 同时执行只读全量采集，3/3 为 `success` 且无采集错误，总墙钟时间 650.28 ms，各 collector 耗时为 258.02–649.21 ms。该小规模并发探测用于检查基本并发兼容，不替代具有代表性的业务并发、数据规模和持续时间测试。

可用 `docker compose exec -T aiops-api python -m scripts.benchmark_health_collection --runs 10 --concurrency 3` 重复执行串行与并发采集测量。2026-11-27 的 5 次串行样本为 5/5 成功，中位数 175.20 ms、P95 340.04 ms；3 路并发样本为 3/3 成功，墙钟 229.57 ms、零错误。2026-11-27 增强报告后以 2 次串行、2 路并发实测，两组均全成功，错误数为 0；样本结构支持按检查和节点定位错误类型及 SQLSTATE，且不复制原始异常文本。该脚本只读目标数据库，直接脚本入口 `python scripts/benchmark_health_collection.py` 也已验证。

### 2026-11-26 周期巡检续跑与 AI 阶段耗时

API 容器重启后，自动巡检配置仍为 enabled、900 秒间隔。调度器在上一条 scheduled 记录超过去重窗口后自然生成新记录 `78666cb2-149f-4470-bdf1-5adffec81f77`，采集状态为 `success`，没有 fallback，Prometheus 周期时间戳随之更新。该轮 collector 耗时为 330.79 ms。

健康审计 evidence 现在分别记录 `collection_duration_ms` 和 `analysis_duration_ms`，并以 `aiops_health_audit_latest_collection_duration_ms`、`aiops_health_audit_latest_analysis_duration_ms` 暴露。SSE 审计 `39e50dff-921e-4e5e-8a4c-bec89b992051` 实测采集耗时 288.46 ms、AI 诊断耗时 36877.32 ms，详情 API 和 Prometheus 均回读到相同数值。该模型耗时说明完整巡检响应时长主要由 AI 阶段决定。

调度器运行状态现通过 `/api/automation/status` 暴露 `state`、当前目标、开始/结束时间、下次重试时间、最近错误类型和连续失败数。Prometheus 暴露 running、连续失败、开始时间和下次重试 gauge，并增加 scheduler failure 告警。API 容器在上一轮计划审计尚处 900 秒去重窗口内重启后，实测状态为 `skipped`，并安排 30 秒后重查，连续失败数为 0。

多目标调度状态按整轮汇总，单个目标失败会保留在 `failed_targets`，后续目标成功不会把本轮伪报为完成。单测覆盖失败后目标成功、整轮状态仍为 `failed` 且按 60 秒重试；当前现场只配置 full target，没有人为制造目标故障。

计划巡检失败现在按连续失败次数指数退避，首轮 60 秒，随后逐步增加，最大值受 `AIOPS_AUTO_AUDIT_RETRY_MAX_SECONDS` 和巡检周期共同约束。跳过周期去重时保持 30 秒后重查，只有整轮所有目标成功才清零失败计数。环境默认上限为 3600 秒，生产使用的实际退避路径通过确定性单测覆盖。

调度器最近完成/失败状态及退避 deadline 保存在 metadata PostgreSQL 的 `aiops_scheduler_runtime` 单行记录中，服务重启后会恢复失败计数并等待剩余退避时间。运行中状态保留在进程内，只有周期终态会写入，避免进程中断后留下永久 `running`。周期去重跳过不覆盖已持久化结果，从而避免多实例中的非执行者覆盖实际执行者状态。

已在真实 metadata PostgreSQL 上验证写入并由新 scheduler 实例恢复 `failed`、错误类型、连续失败数和目标列表，随后恢复了原状态/清理测试记录；API 进程内 scheduler 状态保持不变。

2026-11-27 又观察到真实自动巡检 `f1a96eb4-5a54-4ca3-93b2-71493662caa5` 完成并持久化 `completed`、目标 `full`、失败数 0 和下次运行时间。重启 API 后状态返回 `restored_from_store=true`，保留原 `next_retry_at`，未立即重复巡检；OpenTenBase 与 metadata readiness 均为 ready。

Operational memory 当前查询为空是预期结果，因为现场没有配置独立修复账号，也没有执行真实写修复。修复流程只有在 `ANALYZE` 通过独立账号执行并完成逐 DN `last_analyze`、OID 等后置验证后才写入经验。此前执行分支的 tuple/dict 访问错误已修复，并由单测验证保存 audit、前置条件、后置验证和 effectiveness 字段。

协调节点的锁证据显示 XID `21973` 同时有已授予的排他事务锁和等待者。关联 GID 在两个 DN 上也有预备事务记录。事务归属方需核对应用与协调器记录后确定处置。处置后重新运行无目标健康巡检，逐项核对 `table_stats`、`index_usage` 和各 DN 统计查询的采集状态。全库统计验收以这些查询实测成功为准。

复测时，CN 和两个 DN 上直接扫描 `pg_class`、`pg_stat_user_tables` 和 `pg_stat_user_indexes` 均返回 `55P03`，`pg_namespace` 读取成功。分别在每个节点上使用独立会话观测 `pg_class` 扫描，超时前均捕获到未授予的 `transactionid ShareLock`。CN 等待本地 XID `21973`，DN1 等待 `11576`，DN2 等待 `11457`。各节点的 `pg_prepared_xacts` 将这些本地 XID 映射到同一 GID `_$XC$21973:cn0001:T:2:1`。

健康巡检采集到真实锁等待，并识别出与 XID `21973` 匹配的 prepared transaction。AI 分析阶段还修复了 DeepSeek OpenAI 兼容接口对空 `function_call` 字段的 422 错误。

### 2026-11-27 现场状态复核

02:52 +08:00 的真实全量只读巡检 `36398a2a-f1fb-489a-87c7-d0020694f9c9` 状态为 `completed`，采集状态为 `success`，采集错误为空。CN 仍有 prepared XID `21973`（GID `_$XC$21973:cn0001:T:2:1`）及两个等待该 XID 的会话。该次巡检和随后从 CN 分别执行的只读 `EXECUTE DIRECT` 查询均未在 DN1、DN2 发现对应 GID 的 prepared 记录；DN 锁等待关系为 0。结构化发现记录 `data_node_participant_status=no_matching_records`，表示已成功采集 DN、但没有匹配记录，不代表采集失败。

同一轮巡检从两个 DN 成功取得 27 条表统计、76 条索引统计和 52 条存储记录，错误数为 0。此前记录的 DN 本地 prepared 事务和目录扫描锁超时属于较早观测，不能据此判断当前 DN 状态。CN 上 prepared 事务与等待者的根因关联仍未由官方 `pg_unlock` / `pg_clean` 诊断接口交叉验证，不能据此自动提交或回滚事务。

### 数据节点目录分段复测

在当前实验集群上，通过 CN 对 DN1 和 DN2 执行相同的只读 `pg_class` 计数查询。查询限定普通表（`relkind = 'r'`），锁超时为 300 ms，语句超时为 2 秒。

| OID 范围 | DN1 | DN2 |
| --- | --- | --- |
| 16384–57354 | `55P03` | `55P03` |
| 57355–65535 | 3 张表 | 3 张表 |
| 65536–100000 | 0 张表 | 0 张表 |

这些区间用于定位本次实验的阻塞范围。全库统计验收仍要求各 DN 的批量查询通过。
