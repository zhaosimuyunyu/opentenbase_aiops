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
| `AIOPS_AUTO_AUDIT_ENABLED` | 是否启用周期健康巡检 | `false` |
| `AIOPS_AUTO_AUDIT_INTERVAL_SECONDS` | 周期巡检间隔秒数，最小 60 秒 | `900` |
| `AIOPS_AUTO_AUDIT_TABLE` | 周期巡检统计目标，支持逗号分隔，例如 `public.orders,public.items` | 空，使用全库采集 |
| `AIOPS_DATA_NODE_TABLE_LIMIT` | 全库巡检每个 DN 的表统计采集上限，超限时报告部分采集 | `200` |
| `AIOPS_APPROVAL_TOKEN` | 修复审批令牌 | 空，审批执行关闭 |
| `AIOPS_APPROVER_TOKENS` | 操作者 ID 到独立令牌的 JSON 对象。启用后由服务端按令牌识别审批人，停用共享令牌 | 空 |
| `AIOPS_REPAIR_DB_USER` | 审批通过后连接同一 CN 和数据库的执行账号 | 空，沿用 `DB_USER` |
| `AIOPS_REPAIR_DB_PASSWORD` | 独立执行账号的密码 | 空 |

OpenTenBase v5.0 实测普通角色执行 `EXECUTE DIRECT` 返回 `42501`。当前巡检的逐 DN 采集以及修复的执行前校验和执行后复查都依赖该命令。配置独立账号可以分离凭据，普通表所有者仍无法完成当前版本的双 DN 修复验证。

### Prometheus 告警

审计库已有巡检记录后，可以用 `psql -v ON_ERROR_STOP=1 -f scripts/index_scheduled_audits.sql`
在线建立调度查询索引。连接目标是审计 PostgreSQL，脚本须在事务块之外运行。
如果建索引被中断，检查 `pg_index.indisvalid`。若索引无效，先用
`DROP INDEX CONCURRENTLY audit_records_scheduled_target_idx` 清理该索引，再重跑脚本。

仓库中的 `monitoring/prometheus.yml` 可用于同一 Docker 网络中的独立 Prometheus 实例。将它和 `aiops-alerts.yml` 放在实例的同一配置目录。

示例将告警发给同一网络内的 `alertmanager:9093`。`monitoring/alertmanager.yml` 提供 webhook 路由，部署时将 `webhook_configs` 的 URL 改为实际接收端地址。

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
docker compose exec -T aiops-api python scripts/verify_otb_compatibility.py --repair-account --table public.orders
```

第三条命令使用配置的独立执行账号进行只读探测。它验证连接和逐 DN 统计读取权限，实际表锁与 `ANALYZE` 权限需要通过隔离表执行验收。

使用报告中的 `summary` 判断探测结果。节点可达且 CN 可连接时，统计查询仍可能失败。请查看具体失败项和错误原因。兼容性探测和全库巡检的验收范围见 [OpenTenBase 兼容性记录](docs/OTB_COMPATIBILITY.md)。

## 📚 使用指南

### 健康监控

1. 进入 "📊 健康监控" 页面
2. 查看集群节点、连接数、复制状态
3. 点击 "生成健康报告" 获取 AI 分析

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
