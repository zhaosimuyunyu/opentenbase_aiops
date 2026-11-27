# OpenTenBase AIOps Platform

![OpenTenBase AIOps](https://img.shields.io/badge/OpenTenBase-AIOps-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

基于 AI 的 OpenTenBase 分布式数据库智能运维平台

## ✨ 功能特性

- 🤖 **智能问答助手** - 基于 DeepSeek 大模型的数据库问题诊断
- 🔁 **周期健康巡检** - 可选定时采集、AI 分析并将审计结果持久化
- 📊 **健康监控** - 实时集群状态监控和健康巡检
- 🔍 **性能诊断** - 锁分析、慢查询检测、表统计
- 🧪 **SQL 风险审核** - 危险语句规则检查与只读 EXPLAIN
- 🌐 **CN/DN 分布式采集** - 节点发现、只读巡检和逐节点失败隔离
- 🧾 **风险审批策略** - 白名单只读工具自动运行，写操作与未知操作要求人工批准
- 🎯 **分布式特性** - 针对 OpenTenBase 分布式架构的专项诊断
- 📈 **可视化报告** - 清晰的 Web 界面和数据展示

## 🏗️ 架构

```
┌─────────────────┐
│   Streamlit UI  │ (Port 8080)
└────────┬────────┘
         │
┌────────▼────────┐
│   FastAPI       │ (Port 8000, Optional)
└────────┬────────┘
         │
┌────────▼────────┐
│   Collectors    │
│   - Cluster     │
│   - Performance │
└────────┬────────┘
         │
┌────────▼────────┐
│  DeepSeek LLM   │
│  (AI Engine)    │
└────────┬────────┘
         │
┌────────▼────────┐
│  OpenTenBase    │
│   (容器化部署)   │
└─────────────────┘
```

## 🚀 快速开始

### 前置条件

- Docker & Docker Compose
- 已运行的 OpenTenBase 集群（容器化）
- DeepSeek API Key

### 1. 环境配置

```bash
# 克隆项目
cd E:\opentenbase\kaiyuan_contribute\opentenbase-aiops

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 DeepSeek API Key
```

### 2. 容器化部署

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 3. 访问服务

- **Web UI**: http://localhost:8088
- **API 文档**: http://localhost:8000/docs (可选)

### 4. 生产运行检查

```bash
# 依赖 readiness 和容器状态
curl http://localhost:8000/health
docker compose ps

# 查看周期巡检、退避和恢复状态
curl http://localhost:8000/api/automation/status

# 重复测量只读采集耗时、并发成功率和 SQLSTATE 错误分布
docker compose exec -T aiops-api python -m scripts.benchmark_health_collection \
  --runs 10 --concurrency 3
```

`/health` 同时检查 OpenTenBase 和 metadata PostgreSQL，并在 `capabilities.ai_analysis.configured` 报告 AI 模型密钥是否已配置。AI 未配置时，数据库和 metadata 依赖仍可 ready，监控端可单独识别 AI 能力不可用。周期巡检状态保存在 metadata PostgreSQL，API 重启后会恢复完成/失败状态和下一次重试时间。benchmark 只读目标数据库，不执行修复操作。

## 📦 项目结构

```
opentenbase-aiops/
├── backend/                 # 后端代码
│   ├── collectors/         # 数据采集模块
│   │   ├── base.py        # 基础采集器
│   │   ├── cluster.py     # 集群状态采集
│   │   └── performance.py # 性能指标采集
│   ├── ai/                # AI 模块
│   │   ├── llm_client.py  # DeepSeek 客户端
│   │   └── knowledge_base.py # 知识库
│   ├── utils/             # 工具类
│   │   ├── config.py      # 配置管理
│   │   ├── db_connector.py # 数据库连接
│   │   └── logger.py      # 日志
│   └── app.py             # FastAPI 应用
├── frontend/              # 前端代码
│   └── app.py            # Streamlit 应用
├── data/                 # 数据目录
│   ├── knowledge_base/   # 知识库
│   └── embeddings/       # 向量数据
├── docker-compose.yml    # Docker Compose 配置
├── Dockerfile            # Docker 镜像
├── requirements.txt      # Python 依赖
└── README.md            # 本文件
```

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DB_HOST` | OpenTenBase 主机 | `otb-node1` |
| `DB_PORT` | OpenTenBase 端口 | `11003` |
| `DB_USER` | 数据库用户 | `opentenbase` |
| `DB_NAME` | 连接的数据库 | `postgres` |
| `DB_PASSWORD` | 数据库密码 | 空 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | **必填** |
| `DEEPSEEK_API_BASE` | API 端点 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `DEEPSEEK_TIMEOUT_SECONDS` | 单次巡检模型请求的超时秒数 | `45` |
| `AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS` | 巡检页面等待 API 响应的超时秒数 | `210` |
| `AIOPS_AUTO_AUDIT_ENABLED` | 是否启用周期健康巡检 | `true` |
| `AIOPS_AUTO_AUDIT_INTERVAL_SECONDS` | 周期巡检间隔秒数，最小 60 秒 | `900` |
| `AIOPS_AUTO_AUDIT_TABLE` | 周期巡检统计目标，支持逗号分隔，例如 `public.orders,public.items` | 空，使用全库采集 |
| `AIOPS_DATA_NODE_TABLE_LIMIT` | 全库巡检每个 DN 的表统计采集上限，超限时报告部分采集 | `200` |
| `AIOPS_SLOW_QUERY_LOG_LOOKBACK_SECONDS` | 从 CN/DN CSV 日志中读取近期慢语句的时间窗口 | `900` |
| `AIOPS_SLOW_QUERY_REDACT_LITERALS` | 脱敏慢日志、活动查询和锁证据中的 SQL 字符串/数字 literal | `true` |
| `AIOPS_APPROVAL_TOKEN` | 修复审批令牌 | 空，审批执行关闭 |
| `AIOPS_APPROVER_TOKENS` | 操作者 ID 到独立令牌的 JSON 对象。启用后由服务端按令牌识别审批人，停用共享令牌 | 空 |
| `AIOPS_INSTANCE_ID` | API 实例标识，用于将重启恢复限定在对应实例 | `opentenbase-aiops-api` |

多副本部署时，每个同时运行的 API 副本需要唯一且重启前后稳定的 `AIOPS_INSTANCE_ID`。实例启动只会中断本实例及旧版未标记实例的未完成 Agent turn 和告警审计任务，避免影响其他副本的后台任务。

交互式智能问答 Agent 处于开发验证模式，提供实时 CN/DN/GTM 诊断、全分类知识检索，以及直接执行任意 SQL 的 `execute_sql` 工具。该聊天工具不做操作关键词拦截、不要求额外审批，可通过 `node_name` 将 SQL 发送到指定注册 CN/DN；未指定节点时走配置的 CN。GTM 使用原生协议，不接受 PostgreSQL SQL，只提供 TCP 诊断。数据库实际权限由 `DB_USER` 决定，工具不会提升或模拟权限。每次调用会记录目标节点、SQL SHA-256、命令类型、行数、错误码和耗时，不在执行审计表中保存 SQL 原文或结果。请在明确的开发/测试环境使用该模式，并由操作人员自行决定发送的语句。

独立 `/api/repairs` 工作流仍保留其具名审批和专用执行器机制，用于计划任务及结构化修复请求。该审批层不会拦截聊天 Agent 的 `execute_sql`。`/api/sql-audit` 仍是可选的静态 SQL 风险分析入口，不是聊天执行器的前置闸门。

当前 OpenTenBase v5.0 环境验证过的基础分布式建表语法为 `DISTRIBUTE BY SHARD(id) TO GROUP default_group` 和 `DISTRIBUTE BY REPLICATION TO GROUP default_group`。该环境拒绝 `DISTRIBUTE BY HASH`，临时表曾报 `default group not defined`。GTM 使用原生协议，不能将其 PostgreSQL 端口当作 SQL 端点。系统提示已注入这些实测方言信息，Agent 仍可继续搜索官方文档查证版本差异。

如果业务表不适合转移给修复账号所有，管理员可以使用 `scripts/install_repair_function.sql` 安装最小权限的 `SECURITY DEFINER` 统计函数。该函数只接受正则校验后的 schema/table，并且只允许管理员维护的 `aiops_admin.repair_targets` 视图中列出的目标。视图默认为空，管理员可按脚本示例将其替换为显式 `VALUES` 白名单，不需要创建分布式配置表。管理员完成函数和目标白名单后，将 `AIOPS_REPAIR_FUNCTION_ENABLED=true` 配合独立非超级用户启用。应用会检查函数确实是 `SECURITY DEFINER` 且当前账号有 `EXECUTE` 权限，否则回退到逐 DN 所有权校验并拒绝越权执行。

也可以使用 `scripts/bootstrap_repair_access.sql` 一次创建非超级用户、安装函数并登记一个允许维护的目标。该文件只接受运行时 `psql -v` 变量，仓库不保存数据库密码。

`cancel_query` 是独立的高风险写操作。系统只从 DN 本地锁等待证据生成建议，并要求人工批准。只有配置独立修复账号、完成隔离环境验证后，管理员才可以设置 `AIOPS_CANCEL_QUERY_ENABLED=true`。执行器会在目标 DN 重新核验 PID、用户、数据库、应用名、查询文本和事务时间，调用 `pg_cancel_backend` 后确认原查询已结束。该开关默认为关闭，不能替代 `pg_unlock` 官方扩展的版本和权限核验。

`POST /api/sql-audit` 接收单条 SQL，返回规则命中和风险等级。对未命中高风险规则的 `SELECT`、`WITH`、`VALUES` 语句，可运行带超时限制的只读 `EXPLAIN (FORMAT JSON)`。多条 SQL 会被拒绝。`GET /api/distributed/nodes` 和 `POST /api/distributed/collect` 从 `pgxc_node` 发现 CN/DN，并运行内置只读检查，逐节点报告连接或查询失败。集群注册地址必须能从 API 容器访问。

`AIOPS_SAFETY_REVIEW_MODEL` 可单独指定安全审查 Agent 使用的模型，留空时复用 `DEEPSEEK_MODEL`。API Base 和密钥沿用 DeepSeek 的 OpenAI 兼容配置，因此也可指向同一兼容网关上的不同模型。
| `AIOPS_REPAIR_DB_USER` | 连接同一 CN 和数据库的普通执行账号，须与 `DB_USER` 不同 | 执行修复时必填 |
| `AIOPS_REPAIR_DB_PASSWORD` | 独立执行账号的密码 | 空 |
| `AIOPS_CANCEL_QUERY_ENABLED` | 是否启用经人工审批的 DN 查询取消执行器 | `false` |
| `AIOPS_AUTO_REPAIR_ENABLED` | 是否允许周期巡检触发自动 `ANALYZE` | `false` |
| `AIOPS_AUTO_REPAIR_TARGETS` | 自动修复目标，必须是显式白名单中的 schema.table | 空 |

自动修复只处理周期巡检中唯一的 `stale_table_statistics` 发现。采集必须完整，目标必须同时通过应用配置和数据库管理员函数白名单，执行前会写入 `automatic_policy` 事件，执行后仍按各 DN 的统计时间戳验证。告警触发和手工巡检不会自动写库。

OpenTenBase v5.0 实测普通角色执行 `EXECUTE DIRECT` 返回 `42501`。配置独立执行账号后，由该账号获取表锁并执行 `ANALYZE`，巡检账号通过单独的只读连接完成执行前和执行后的逐 DN 统计检查。两条连接必须指向同一集群和数据库。

### Prometheus 告警

审计库已有巡检记录后，可以用 `psql -v ON_ERROR_STOP=1 -f scripts/index_scheduled_audits.sql`
在线建立调度查询索引。连接目标是审计 PostgreSQL，脚本须在事务块之外运行。
如果建索引被中断，检查 `pg_index.indisvalid`。若索引无效，先用
`DROP INDEX CONCURRENTLY audit_records_scheduled_target_idx` 清理该索引，再重跑脚本。

仓库中的 `monitoring/prometheus.yml` 可用于同一 Docker 网络中的独立 Prometheus 实例。将它和 `aiops-alerts.yml` 放在实例的同一配置目录。

示例将告警发给同一网络内的 AIOps API。`monitoring/alertmanager.yml` 默认使用 `http://aiops-api:8000/api/alerts`，firing 告警会创建后台只读 Agent 审计任务，结果写入巡检历史。通过 `GET /api/alerts/{task_id}` 查询任务状态。resolved 告警只记录为忽略，不会重复触发巡检。

将 AIOps API 的 `/metrics` 加入现有 Prometheus，抓取任务名设为 `opentenbase-aiops`。
在同一 Docker 网络中使用 `aiops-api:8000`，在宿主机运行 Prometheus 时使用 `127.0.0.1:8000`。
通过 Prometheus 的 `rule_files` 加载仓库中的 `monitoring/aiops-alerts.yml`，并用现有 Alertmanager 路由投递告警。
规则覆盖高风险、定时巡检超期、指标抓取失败、采集不完整和模型诊断回退。

周期巡检默认关闭。配置启用后由 API 服务定期运行只读健康审计，结果写入巡检历史。多 API 实例通过知识库 PostgreSQL advisory lock 选出单一巡检者。手动巡检也经过 API 并使用同一把锁。

### OpenTenBase 连接

项目通过 **psycopg2** 连接 OpenTenBase：

```python
# 容器内直接连接
conn = psycopg2.connect(
    host="otb-node1",
    port=11003,
    user="opentenbase",
    dbname="postgres"
)
```

默认 Compose 配置需要预先存在的外部网络 `otb-lab-net`。使用不同部署拓扑时，确保 API 容器能访问配置的 CN 和 `pgxc_node` 公布的节点地址。

使用当前仓库构建并启动 API 后，从项目目录运行只读兼容性探测。第二条命令适用于需要验收单表统计的环境，请将表名替换成实际存在的表。

```powershell
docker compose exec -T aiops-api python scripts/verify_otb_compatibility.py
docker compose exec -T aiops-api python scripts/verify_otb_compatibility.py --table public.orders
docker compose exec -T aiops-api python scripts/verify_otb_compatibility.py --repair-account
```

第三条命令使用独立执行账号检查登录和数据库身份。巡检账号的逐 DN 权限通过前两条命令验证。执行账号的表锁可在隔离表上加 `--repair-lock --table public.orders` 验证，`ANALYZE` 权限需通过执行验收。

对隔离数据库完整验证健康巡检、独立账号提案、人工审批、`ANALYZE` 和逐 DN 后置条件，可运行：

```powershell
docker compose exec -T aiops-api python scripts/verify_analyze_repair.py --database lab
```

该脚本使用 OpenTenBase 管理连接创建随机命名的临时表和非超级用户，只对这个临时对象执行写入与 `ANALYZE`。执行结束后会删除临时表、角色及对应的审计、修复和 memory 记录。要求当前账号有创建/删除角色和对象的权限，`lab` 中存在 `default_group`，且已配置可用的 DeepSeek 和知识库服务。完成验收后应检查 JSON 输出中的 `status=passed`、`request_status=executed` 和 `postcondition.verified=true`。

使用报告中的 `summary` 判断探测结果。节点可达且 CN 可连接时，统计查询仍可能失败。请查看具体失败项和错误原因。兼容性探测和全库巡检的验收范围见 [OpenTenBase 兼容性记录](docs/OTB_COMPATIBILITY.md)。

## 📚 使用指南

### 健康监控

1. 进入 "📊 健康监控" 页面
2. 查看集群节点、连接数、复制状态
3. 点击 "生成健康报告" 获取 AI 分析

巡检同时读取各 CN/DN 最近的 CSV 慢语句日志，只报告配置时间窗口内完成的语句。仅当 OpenTenBase 的 `log_min_duration_statement` 启用时，超过数据库阈值的语句会进入巡检证据。默认会将 SQL 字符串和数字 literal 替换为占位符、移除注释并保留脱敏语句形状指纹；`AIOPS_SLOW_QUERY_REDACT_LITERALS=false` 会让 literal 进入审计和模型上下文，仅应在隔离调试环境使用。升级前已写入数据库的历史行不会自动改写，相关审计和修复读取接口会在返回及重新分析前脱敏。

### 智能问答

1. 进入 "💬 智能问答" 页面
2. 输入问题，例如：
   - "如何优化慢查询？"
   - "主从延迟过高怎么办？"
   - "连接数快满了怎么处理？"
3. AI 会结合当前集群状态给出诊断和建议

### 性能诊断

1. 进入 "🔍 性能诊断" 页面
2. 选择诊断维度：
   - **锁分析**: 检测死锁和阻塞
   - **长查询**: 发现性能瓶颈
   - **表统计**: 分析表使用情况

## 🛠️ 开发指南

### 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Streamlit (开发模式)
streamlit run frontend/app.py --server.port 8080

# 启动 FastAPI (可选)
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
```

### 添加新功能

1. **新采集器**: 在 `backend/collectors/` 创建新模块
2. **新 AI 功能**: 在 `backend/ai/` 扩展 LLM 客户端
3. **新页面**: 在 `frontend/pages/` 添加新页面

## 🧪 测试

```bash
# 运行测试
pytest tests/

# 测试数据库连接
python scripts/test_connection.py
```

## 📖 API 文档

启动服务后访问: http://localhost:8000/docs

主要端点：
- `GET /health` - 健康检查
- `GET /api/cluster/status` - 集群状态
- `GET /api/performance/metrics` - 性能指标
- `POST /api/qa/ask` - 智能问答
- `GET /api/health-report` - 健康报告

## 🎯 特色功能

### 分布式诊断

针对 OpenTenBase 分布式特性的专项诊断：

- ✅ 跨节点协调问题检测
- ✅ 全局事务死锁分析
- ✅ 分片分布不均衡检测
- ✅ 分布式查询优化建议

### AI 驱动

- 🤖 基于 DeepSeek 的智能推理
- 📚 可扩展的知识库系统
- 🎯 上下文感知的问题诊断
- 💡 可解释的优化建议

## 🤝 贡献指南

欢迎贡献到 OpenTenBase AIOps 项目！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 License

MIT License

## 👥 作者

OpenTenBase AIOps 开发团队

## 🙏 致谢

- [OpenTenBase](https://github.com/OpenTenBase/OpenTenBase) - 企业级分布式 HTAP 数据库
- [DeepSeek](https://www.deepseek.com/) - AI 大模型支持
- [Streamlit](https://streamlit.io/) - 快速构建数据应用

## 📮 联系方式

- 提交 Issue: [GitHub Issues](https://github.com/OpenTenBase/AIOPS/issues)
- 邮箱: devingeng@tencent.com

---

⭐ 如果这个项目对您有帮助，请给我们一个 Star！
### Audit analysis retry

`POST /api/audits/{audit_id}/reanalyze` reruns the model analysis from persisted read-only evidence. It does not recollect the database or execute SQL, and the stored finding severity remains the minimum risk level.
