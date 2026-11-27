# OpenTenBase AIOps 最终验收报告

更新时间：2026-11-27

## 1. 课程要求对照

课程 PPT 的 AIOps 题目要求结合 OpenTenBase/TXSQL 常见错误、运维问题和官方文档，完成可演示的 AIOps 应用，并提交 demo、设计说明和结果分析。题目列出的功能包括智能问答、健康巡检、锁/会话异常诊断、慢 SQL 诊断和 SQL 审核，单一模块或完整模块均可提交。

| 要求 | 当前证据 | 判定 |
|---|---|---|
| 可演示应用 | Docker Compose、Streamlit `:8088`、FastAPI `:8000`、`/health` ready | 已完成 |
| 智能问答 | 多轮 Agent、SSE、会话持久化、知识检索和实时数据库工具 | 已完成 |
| 智能化监控 | 周期只读巡检、CN/DN 采集、SSE 进度、审计持久化、失败退避 | 已完成 |
| 会话异常诊断 | `pg_locks`、阻塞会话、prepared transaction 证据；`simulate_lock_wait.py` 实测 | 已完成 |
| 慢 SQL 诊断 | `simulate_slow_query.py` 通过 CSV 慢日志捕获自然结束的 `pg_sleep`，进入 SSE 审计 | 已完成，但属于事后日志诊断 |
| SQL 审核 | 静态规则、单条语句校验、只读 EXPLAIN、顺序扫描估算风险 | 部分完成 |
| 官方知识库 | pgvector 中 68 份文档、3502 个向量片段，在线检索回归通过 | 已完成 |
| 设计说明 | 架构、兼容性、课程交付和路线图文档 | 已完成 |
| 结果分析 | 本报告、兼容性报告和课程交付说明 | 已完成 |

课程提交仍需要学生自己保存演示日志，并向上游 OpenTenBase 社区提交 Issue、文档、工具或 PR。仓库提交不能替代社区贡献记录，理论学习 20% 也不能从代码仓库证明。

## 2. 真实环境验收

- OpenTenBase v5.0 / PostgreSQL 10 兼容标识：API 连接成功。
- CN/DN 只读健康巡检：跨节点采集成功，既有 prepared transaction 会使部分目录检查出现 `55P03` 时会保留 partial 证据。
- ANALYZE 修复闭环：真实创建隔离表和专用非超级用户，经 AI 分析、提案、具名人工审批、执行和双 DN 后置验证通过，临时对象与元数据清理完成。
- SQL 审核真实验证：`SELECT * FROM pg_catalog.pg_class` 的只读 EXPLAIN 产生 `Seq Scan`，默认阈值下返回 `sequential_scan_review`。临时阈值为 1 时返回 `large_sequential_scan` 和 high 风险。输入 SQL 未执行。
- 采集基准：10 次顺序、3 路并发均成功且零错误。追加的 30 秒、2 worker 持续只读采集完成 230 次，230/230 成功，错误数 0，中位数 266.75 ms，P95 308.59 ms，最大 339.81 ms。
- 元数据库恢复：custom-format 备份带 SHA-256，临时库和隔离新库恢复核对通过，核心表行数包含 68 份知识文档、3502 个向量片段和 205 条审计。

## 3. 生产要求对照

### 已具备

- Docker Compose、健康检查、重启策略和 metadata 备份 profile。
- API 可选 Bearer key、UI 可选共享密码、CORS 配置。
- 只读采集超时和锁超时，逐节点失败隔离。
- SQL 证据默认字面量脱敏，历史审计/修复 JSON 可迁移清理。
- 结构化 ANALYZE 修复的审批、专用账号、执行审计和后置验证。
- Agent turn、周期巡检状态、审计、修复事件和 operational memory 持久化。

### 尚未达到

- UI/API 共享 key 不是用户身份、RBAC、key 轮换或速率限制系统。
- 交互式 Agent 的 `execute_sql` 在开发模式按 `DB_USER` 直接执行，不经过 SQL 审核或审批。生产必须使用独立只读/执行账号、外部认证和网络隔离。
- `SECURITY DEFINER` 修复函数在当前 OpenTenBase v5.0 兼容性仍未解决。
- `cancel_query`、prepared transaction 恢复、DROP/重启等操作没有生产执行器。
- 当前性能数据是课程实验集群低负载样本，不构成容量、SLO 或业务影响基线。
- 备份 profile 没有异地副本、WAL/PITR，也不覆盖 OpenTenBase 业务数据。
- 没有多副本 API、负载均衡、集中密钥管理和完整灾备演练。
- SQL 审核没有接入外部发布流水线，不估算事务总写入量。

## 4. 交付命令

下载后先按 [连接说明](../README.md#opentenbase-连接) 配置实际 CN 的 PostgreSQL 协议地址、SQL 端口、数据库和账号。默认 Compose 自建应用网络，已有课程集群按连接说明使用 `compose.lab.yml`。用 `/health` 检查 CN 连通性，再用兼容性脚本验证节点直连、系统视图和权限。本文的实机结果来自 OpenTenBase v5.0 实验集群。

```powershell
git clone https://github.com/zhaosimuyunyu/opentenbase_aiops.git
cd opentenbase_aiops
Copy-Item .env.example .env
# 编辑 .env 后再启动
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:8000/health
powershell -ExecutionPolicy Bypass -File .\scripts\course_demo.ps1 -SkipLiveAgent
```

需要真实模型问答时去掉 `-SkipLiveAgent` 并填写 `DEEPSEEK_API_KEY`。课程演示前应保存 `Start-Transcript` 日志，并在结果分析中说明慢 SQL 是日志驱动的事后识别。
