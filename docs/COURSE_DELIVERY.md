# OpenTenBase 秋季课程交付对照

## 课程评分项

课程考核由理论学习 20%、实践任务 40%、开源贡献 40% 组成。实践方向包括数据库工程、Agent CLI/Skill 工具和 AIOps 应用。AIOps 方向要求提供可演示应用、设计说明和结果分析，可按课程要求提交一个完整模块。

本项目选择 AIOps 应用方向，目前没有实现独立的 CLI/Skill 打包作业或数据库内核分区查询进阶任务。

| 课程模块 | 当前实现 | 证据 | 状态 |
|---|---|---|---|
| 智能问答 | 多轮 LLM Agent，支持实时拓扑/锁、知识库和任意 SQL 工具 | `/api/qa/ask` 工具轨迹及真实 SQL 操作 | 已演示 |
| 智能化监控 | 每 900 秒执行只读健康巡检，支持 SSE 和审计持久化 | `/api/automation/status` 和巡检历史 | 已运行，当前部分目录/统计检查受既有锁超时影响 |
| 会话异常诊断 | CN/DN 锁等待、阻塞会话身份和 prepared transaction 证据 | `backend/tools/simulate_lock_wait.py` 模拟真实 DN advisory lock 等待 | 已演示 |
| 慢 SQL 分析 | 读取 CN/DN 的 `pg_stat_activity` 与 CSV 慢语句日志，结合 SQL 风险检查、只读 `EXPLAIN` 和 AI 建议 | `backend/tools/simulate_slow_query.py` 经 CN 入口运行超过数据库日志阈值的 `pg_sleep`，自然结束后由 SSE 巡检从 CN/DN 日志捕获 PID、SQL 和耗时 | 已验证已完成语句的日志诊断 |
| SQL 审核 | 静态风险规则和受支持语句的只读 explain | SQL 审核 API 与测试套件 | 已演示，尚未接入发布流水线 |
| 知识库 | 固定版本 OpenTenBase 文档和源码引用，存于 pgvector | 68 份资料、3502 个向量块和在线检索回归 | 已演示 |
| 部署 | Docker Compose、健康检查、重启策略和定时只读巡检 | `docker compose ps`、`/health` | 已运行 |

慢 SQL 端到端验收在 2026-11-26 通过：审计 `ab75ef96-701b-458d-a5ae-0ee6dff68e49` 从 `cn0001` 捕获 PID `6537`、应用名 `aiops-course-slow-query-demo`、`SELECT pg_sleep(15)` 和 `15058.491 ms`。SSE 依次输出 progress 并返回 result，模拟会话自然结束，AI 分析来源为 deterministic_evidence_rules，引用 3 条知识库资料。随后又以同一环境验证审计 `2139ff08-b9db-4346-b9c4-915ae227785a`，同样捕获慢 SQL 日志证据。

## 已验收 SQL 演示

实时 Agent 通过配置的 CN 和当前数据库账号完成了：

1. 使用 `DISTRIBUTE BY SHARD(id) TO GROUP default_group` 创建隔离测试表。
2. 插入两行测试数据。
3. 读回数据并核验行数与值。
4. 删除测试表并确认 `to_regclass` 返回 `NULL`。

每次工具调用均记录在 `agent_sql_execution_audit`。演示表已清理。Agent 还获取并释放了 session advisory lock，并实测直连 `dn0001` 执行 SQL。

## 复现实验

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\course_demo.ps1
```

脚本检查 API/数据库健康、Agent 和自动巡检能力、实时 Agent 环境检查、官方知识检索回归、隔离 SHARD 表写入/清理、超过服务端日志阈值的慢查询及 SSE 审计、DN 锁等待 SSE 审计、SQL 审核和单元测试。慢查询模拟会等 `pg_sleep` 自然结束，再验证审计是否包含匹配 PID、应用名、SQL 与耗时。实时 Agent 调用可能需要数分钟。模型网关不可用时可用 `-SkipLiveAgent` 跳过实时问答，其余集成检查仍会运行。

`backend/`、`frontend/` 和 `scripts/` 都挂载到运行容器。源码、课程脚本和文档更新后重启服务即可生效；增加 Python 依赖或修改基础镜像时才需要重建镜像。

To preserve a demo transcript:

```powershell
New-Item -ItemType Directory -Force .\artifacts | Out-Null
Start-Transcript -Path .\artifacts\course-demo.txt
powershell -ExecutionPolicy Bypass -File .\scripts\course_demo.ps1
Stop-Transcript
```

## 当前边界

- 当前 `DB_USER=opentenbase` 实测是超级用户。交互式 `execute_sql` 直接使用该账号，不做 SQL 审批或关键词拦截。这是课程开发验证模式，不是生产最小权限配置。
- `AIOPS_AUTO_REPAIR_ENABLED` 和 `AIOPS_CANCEL_QUERY_ENABLED` 仍关闭。结构化修复请求仍要求独立修复账号并使用配置的审批流程。
- 当前 OpenTenBase v5.0 实测支持 `SHARD` 语法。`DISTRIBUTE BY HASH` 在此实例失败，`CREATE TEMP TABLE` 曾返回 default group 错误，因此 Demo 使用显式分布的普通表并在结束后删除。
- GTM 使用原生协议。Agent 只报告注册拓扑和 TCP 可达性，不从 GTM 端口执行 PostgreSQL SQL。
- 既有 prepared transaction 锁会使部分目录/统计检查超时，巡检报告会标记 `partial` 并保留错误证据。
- 本实例上正在运行的查询在 CN 和 DN 的 `pg_stat_activity` 都显示 `state=idle`、`query_start=null`、`query=""`。慢查询因此通过数据库 CSV 日志里的 `duration: ... statement: ...` 记录在语句结束后识别，不是运行中实时识别。
- 当前实例 `log_min_duration_statement=10000`。采集器逐个连接注册的 CN/DN，通过 `pg_ls_dir`、`pg_stat_file` 和 `pg_read_file` 只读最近两个 CSV 文件的尾部，每个文件最多 8 MiB，并只报告 `AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS` 时间窗口内的新记录，默认 900 秒，与默认巡检间隔相同。
- 日志访问使用当前数据库账号。CSV 日志包含 SQL 文本，巡检会把匹配语句持久化到审计证据；当前课程环境的账号是超级用户。生产环境需单独评估日志读取授权、SQL 中的敏感常量和日志采集对节点的开销。

## 剩余课程工作

智能问答、智能化监控、会话异常诊断、已完成语句的慢 SQL 诊断和 SQL 审核均有运行证据。慢 SQL 检测是服务端日志驱动的事后分析，当前实例不能从活动视图实时识别运行中的语句。提交时应保存一键 Demo 日志，并在结果分析中说明这一时效边界。

仅有本仓库提交不能证明课程的开源贡献项。学生还需向上游提交 Issue、文档/工具贡献或 PR，并保存社区链接、讨论和根据反馈修改的记录。我不会代发该社区 Issue。

理论学习占 20%，还需由课程课堂参与记录或技术文章证明，无法从本仓库确认。
