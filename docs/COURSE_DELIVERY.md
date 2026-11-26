# OpenTenBase 秋季课程交付对照

## 课程评分项

课程考核由理论学习 20%、实践任务 40%、开源贡献 40% 组成。实践方向包括数据库工程、Agent CLI/Skill 工具和 AIOps 应用。AIOps 方向要求提供可演示应用、设计说明和结果分析，可按课程要求提交一个完整模块。

本项目选择 AIOps 应用方向，目前没有实现独立的 CLI/Skill 打包作业或数据库内核分区查询进阶任务。

| 课程模块 | 当前实现 | 证据 | 状态 |
|---|---|---|---|
| 智能问答 | 多轮 LLM Agent，支持实时拓扑/锁、知识库和任意 SQL 工具 | `/api/qa/ask` 工具轨迹及真实 SQL 操作 | 已演示 |
| 智能化监控 | 每 900 秒执行只读健康巡检，支持 SSE 和审计持久化 | `/api/automation/status` 和巡检历史 | 已运行，当前部分目录/统计检查受既有锁超时影响 |
| 会话异常诊断 | CN/DN 锁等待、阻塞会话身份和 prepared transaction 证据 | `backend/tools/simulate_lock_wait.py` 模拟真实 DN advisory lock 等待 | 已演示 |
| 慢 SQL 分析 | CN/DN 长查询采集、SQL 风险检查、只读 `EXPLAIN` 和 AI 建议 | `backend/tools/simulate_slow_query.py` 在 DN 上运行隔离 `pg_sleep` 查询并通过 SSE 巡检核验捕获 | 采集逻辑已实现，本实例尚未验收捕获 |
| SQL 审核 | 静态风险规则和受支持语句的只读 explain | SQL 审核 API 与测试套件 | 已演示，尚未接入发布流水线 |
| 知识库 | 固定版本 OpenTenBase 文档和源码引用，存于 pgvector | 68 份资料、3502 个向量块和在线检索回归 | 已演示 |
| 部署 | Docker Compose、健康检查、重启策略和定时只读巡检 | `docker compose ps`、`/health` | 已运行 |

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

脚本检查 API/数据库健康、Agent 和自动巡检能力、实时 Agent 环境检查、官方知识检索回归、隔离 SHARD 表写入/清理、慢查询采集尝试与 SSE 审计、DN 锁等待 SSE 审计、SQL 审核和单元测试。慢查询若未被本实例的活动视图捕获，会输出 `not_captured` 和审计证据，脚本继续验证其余功能。实时 Agent 调用可能需要数分钟。模型网关不可用时可用 `-SkipLiveAgent` 跳过实时问答，其余集成检查仍会运行。

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
- 本实例的慢查询活动采集仍需结合 `not_captured` 报告核查。模拟 SQL 使用 DN 直连 `pg_sleep`，但当前版本曾在 DN `pg_stat_activity` 中显示为空闲且无 `query_start`，因此该课程项暂不能算通过。

## 剩余课程工作

智能问答、智能化监控、会话异常诊断和 SQL 审核已有运行证据。慢 SQL 诊断实现了采集与审计路径，但在当前 OpenTenBase 实例上尚未证实能捕获正在执行的慢查询。提交时应保存一键 Demo 日志，并在结果分析中记录该限制。

仅有本仓库提交不能证明课程的开源贡献项。学生还需向上游提交 Issue、文档/工具贡献或 PR，并保存社区链接、讨论和根据反馈修改的记录。我不会代发该社区 Issue。

理论学习占 20%，还需由课程课堂参与记录或技术文章证明，无法从本仓库确认。
