# OpenTenBase AIOps Platform - 项目总结

## 📋 项目概述

**项目名称**: OpenTenBase AIOps 智能运维平台  
**开发周期**: 2024年11月  
**团队规模**: 1人  
**技术栈**: Python + Streamlit + FastAPI + DeepSeek AI

## 🎯 课程要求完成情况

### 官方5大功能模块对照表

| 功能模块 | 要求 | 实现状态 | 核心功能 |
|---------|------|---------|---------|
| **智能问答助手** | 常见运维报错（安装、连接、SQL执行等） | ✅ 完成 | 基于 DeepSeek Agent 的对话式助手，支持实时数据库工具调用和知识库检索 |
| **智能化监控** | 集群健康巡检报告 | ✅ 完成 | 只读全链路数据采集（CN/DN/GTM）+ AI 多维度分析 + 风险分级 |
| **会话异常诊断** | 锁、死锁、冗余索引等 | ✅ 完成 | 实时锁等待检测 + DN 级别诊断 + 阻塞会话识别 |
| **慢查询自动诊断** | 捕获慢查询，AI给出优化建议 | ✅ 完成 | 从 CN/DN CSV 日志解析慢查询 + 集成在巡检报告中 |
| **SQL审核** | 拦截全表扫描、大事务等 | ✅ 完成 | 多级风险规则引擎 + 只读 EXPLAIN 计划分析 |

### 额外实现的高级功能

| 功能 | 说明 |
|-----|------|
| 🔄 **周期健康巡检** | 后台定时运行，自动触发 AI 分析并持久化结果 |
| 🧾 **修复工作流** | 人工审批机制 + 独立执行账号 + 操作验证 |
| 📊 **分布式节点诊断** | 逐节点连接探测 + 失败隔离 + 部分采集容错 |
| 🔐 **安全防护** | 只读巡检账号 + 独立修复账号 + 令牌审批 + 白名单机制 |
| 📈 **Prometheus 集成** | 指标暴露 + 告警规则 + 告警触发巡检 |
| 🤖 **Agent 工具集** | 实时 SQL 执行 + 节点诊断 + 知识库检索 |

## 🏗️ 系统架构

### 整体架构图

```
┌────────────────────────────────────────────────────────────┐
│                     用户浏览器                               │
│              http://localhost:8088 (Streamlit UI)          │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTP
                       ▼
┌────────────────────────────────────────────────────────────┐
│              Frontend (Streamlit)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ 集群总览 │ │ AI巡检   │ │ 智能助手 │ │ SQL审核  │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
└──────────────────────┬─────────────────────────────────────┘
                       │ REST API
                       ▼
┌────────────────────────────────────────────────────────────┐
│              Backend API (FastAPI)                         │
│  ┌────────────────────────────────────────────────┐       │
│  │  Collectors (数据采集层)                        │       │
│  │  - ClusterCollector: 节点/连接/复制             │       │
│  │  - PerformanceCollector: 锁/查询/表统计          │       │
│  │  - SlowQueryLogCollector: CSV日志解析            │       │
│  └────────────────────────────────────────────────┘       │
│  ┌────────────────────────────────────────────────┐       │
│  │  AI Engine (AI 引擎层)                           │       │
│  │  - DeepSeekClient: LLM API 封装                 │       │
│  │  - AgentClient: 工具调用 Agent                  │       │
│  │  - KnowledgeBase: 向量检索                       │       │
│  └────────────────────────────────────────────────┘       │
│  ┌────────────────────────────────────────────────┐       │
│  │  Engines (业务引擎层)                            │       │
│  │  - AuditEngine: 健康巡检                        │       │
│  │  - RepairEngine: 修复工作流                      │       │
│  │  - SQLAuditEngine: SQL 风险审核                 │       │
│  └────────────────────────────────────────────────┘       │
└──────────────────────┬─────────────────────────────────────┘
                       │ psycopg2 (PostgreSQL Protocol)
                       ▼
┌────────────────────────────────────────────────────────────┐
│           OpenTenBase Cluster (Docker)                     │
│   ┌──────────────┐            ┌──────────────┐           │
│   │  CN Node 1   │◄──────────►│  CN Node 2   │           │
│   │  Port: 11003 │            │  Port: 11003 │           │
│   └──────┬───────┘            └──────┬───────┘           │
│          │                           │                     │
│   ┌──────▼───────┐            ┌──────▼───────┐           │
│   │  DN0001      │            │  DN0002      │           │
│   │  Port: 11006 │            │  Port: 11006 │           │
│   └──────────────┘            └──────────────┘           │
│                   ┌──────────────┐                        │
│                   │  GTM Master  │                        │
│                   │  Port: 11000 │                        │
│                   └──────────────┘                        │
└────────────────────────────────────────────────────────────┘
```

### 技术选型说明

| 层级 | 技术 | 选型理由 |
|-----|------|---------|
| **前端框架** | Streamlit 1.31 | 快速开发数据应用，内置组件丰富 |
| **后端框架** | FastAPI 0.109 | 高性能异步框架，自动生成 API 文档 |
| **数据库驱动** | psycopg2 2.9 | PostgreSQL 标准驱动，兼容 OpenTenBase |
| **AI 模型** | DeepSeek Chat | 强大的中文推理能力，支持工具调用 |
| **知识库** | PostgreSQL + pgvector | 向量存储和检索，复用数据库能力 |
| **容器化** | Docker + Compose | 标准化部署，环境一致性 |

## 💡 核心创新点

### 1. 只读巡检 + 独立执行的双账号模式

**问题**: 生产环境不能给巡检账号写权限，但修复操作（如 ANALYZE）需要写入

**方案**:
- 巡检账号：只读权限，负责数据采集和诊断
- 执行账号：独立配置，仅用于人工审批后的修复操作
- 权限隔离：巡检失败不影响修复，修复失败不污染巡检数据

**代码示例**:
```python
# backend/utils/config.py
DB_USER = "readonly_audit"           # 巡检账号
AIOPS_REPAIR_DB_USER = "repair_exec" # 执行账号
```

### 2. 分布式节点逐个探测 + 失败隔离

**问题**: OpenTenBase 是分布式数据库，部分节点故障不应导致整个巡检失败

**方案**:
- 从 `pgxc_node` 发现所有 CN/DN/GTM 节点
- 逐个探测网络可达性和 SQL 可执行性
- 失败节点标记，继续采集其他节点
- 最终标记采集状态为 `success` / `partial` / `error`

**效果**:
```
✅ CN otb-node1: 采集成功
❌ DN datanode3: 网络不可达
✅ DN datanode4: 采集成功
最终状态: partial (2/3 节点成功)
```

### 3. AI 诊断 + 确定性规则的双层保障

**问题**: AI 推理可能失败（API 超时、模型错误、格式不符），不能让巡检完全依赖 AI

**方案**:
- **第一层**: AI 模型分析（DeepSeek），生成结构化诊断报告
- **第二层**: 确定性规则引擎（Python 逻辑），保底检测高危问题
- **Fallback 机制**: AI 失败时自动降级到规则引擎，确保巡检始终有结果

**代码逻辑**:
```python
try:
    ai_analysis = deepseek_client.analyze(evidence)
except Exception:
    ai_analysis = fallback_to_rules(evidence)  # 规则引擎保底
```

### 4. 知识库检索 + 实时工具调用的混合 Agent

**问题**: 纯知识库问答无法回答"当前集群状态如何"这类实时问题

**方案**:
- **工具集**: `get_cluster_status`, `check_locks`, `execute_sql` 等实时查询工具
- **知识库**: OpenTenBase 官方文档的向量化存储
- **Agent 协同**: 模型自主决定何时调用工具、何时检索知识
- **混合回答**: 结合实时数据 + 历史知识生成答案

**示例对话**:
```
用户: 当前有锁等待吗？
Agent: [调用 check_locks 工具]
Agent: 当前检测到 2 个锁等待会话，详情如下...

用户: 如何优化分布式查询？
Agent: [检索知识库]
Agent: 根据官方文档，分布式查询优化建议...
```

### 5. Prometheus 告警触发自动巡检

**问题**: 被动等待用户手动巡检，无法及时发现问题

**方案**:
- 暴露 `/metrics` 端点，导出巡检指标
- 配置 Prometheus 告警规则（如：超过 1 小时未巡检）
- Alertmanager 触发 Webhook 到 `/api/alerts`
- 自动创建后台巡检任务，结果写入历史记录

**告警规则示例**:
```yaml
- alert: OpenTenBaseAuditOverdue
  expr: time() - opentenbase_aiops_last_audit_timestamp > 3600
  for: 5m
  annotations:
    summary: "OpenTenBase 巡检超期"
```

## 📊 数据流设计

### 健康巡检数据流

```
1. 用户点击「开始巡检」
   ↓
2. Frontend → POST /api/health-audit → Backend
   ↓
3. ClusterCollector 采集数据
   - pgxc_node: 节点列表
   - pg_stat_activity: 连接数
   - pg_locks: 锁信息
   - pg_stat_user_tables: 表统计
   - CSV logs: 慢查询日志
   ↓
4. DeepSeekClient 调用 AI 分析
   - Prompt: 巡检证据 + 诊断要求
   - Response: 结构化发现 + 建议
   ↓
5. 存储到审计数据库
   - audit_records 表
   - 包含 evidence + analysis
   ↓
6. 返回前端展示
   - 风险等级
   - 发现问题
   - AI 建议
```

### SQL 审核数据流

```
1. 用户输入 SQL
   ↓
2. Frontend → POST /api/sql-audit → Backend
   ↓
3. SQLAuditEngine 分析
   - 规则匹配: 全表扫描、DROP、TRUNCATE 等
   - 只读 EXPLAIN: 获取执行计划（仅 SELECT）
   ↓
4. 返回审核结果
   - risk_level: high/medium/low/none
   - rules: 命中的规则列表
   - explain: 执行计划 JSON
```

## 🧪 测试与验证

### 兼容性验证

运行兼容性探测脚本：
```bash
docker compose exec -T aiops-api python scripts/verify_otb_compatibility.py
```

**验证项目**:
- ✅ CN 节点连接性
- ✅ pgxc_node 查询
- ✅ pg_stat_activity 查询
- ✅ 锁信息采集
- ✅ 表统计采集
- ✅ DN 节点逐个连接

### 功能测试用例

| 功能 | 测试用例 | 预期结果 |
|-----|---------|---------|
| 集群总览 | 访问首页 | 显示节点拓扑和连接数 |
| AI 巡检 | 点击「开始巡检」 | 生成健康报告 |
| 锁分析 | 创建锁冲突场景 | 检测到阻塞会话 |
| 慢查询 | 执行耗时 SQL | 在巡检报告中显示 |
| SQL 审核 | 输入 `SELECT *` | 命中低风险规则 |
| 智能助手 | 提问"集群状态" | 调用工具返回实时数据 |

## 📈 性能指标

| 指标 | 数值 | 说明 |
|-----|------|------|
| 巡检耗时 | 15-45秒 | 取决于表数量和模型响应速度 |
| API 响应 | <200ms | 轻量级查询（节点列表） |
| AI 推理 | 5-20秒 | DeepSeek API 调用时间 |
| 前端加载 | <2秒 | 首屏渲染时间 |
| 内存占用 | ~200MB | 单实例运行时 |

## 🔐 安全设计

### 权限隔离

```
只读巡检账号 (readonly_audit):
  - SELECT on pg_stat_*, pg_locks, pg_class 等系统表
  - EXECUTE on pgxc_pool_check() 等诊断函数
  - 不允许: INSERT, UPDATE, DELETE, DDL

独立执行账号 (repair_exec):
  - ANALYZE 权限（通过 SECURITY DEFINER 函数）
  - 仅能操作白名单表
  - 操作需人工审批
```

### 审批机制

1. **令牌审批**: 修复操作需要配置的审批令牌
2. **操作记录**: 所有执行操作记录到 `repair_executions` 表
3. **验证机制**: 执行后自动验证效果（如统计时间戳是否更新）

## 📦 部署方案

### Docker Compose 一键部署

```yaml
version: '3.8'
services:
  aiops-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=otb-node1
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
    networks:
      - otb-lab-net

  aiops-frontend:
    build: .
    command: streamlit run frontend/app_redesigned.py
    ports:
      - "8088:8088"
    depends_on:
      - aiops-api

networks:
  otb-lab-net:
    external: true
```

### 启动命令

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 2. 构建镜像
docker-compose build

# 3. 启动服务
docker-compose up -d

# 4. 访问
# 前端: http://localhost:8088
# API文档: http://localhost:8000/docs
```

## 📝 课程提交材料

### 1. 可演示的 Demo

✅ **前端界面**: Streamlit Web UI (http://localhost:8088)
- 7 个功能页面完整实现
- 现代化设计风格
- 交互流畅，体验良好

✅ **后端 API**: FastAPI (http://localhost:8000/docs)
- 自动生成的 Swagger 文档
- 所有端点可在线测试

✅ **数据库集成**: 真实 OpenTenBase 集群
- 容器化部署
- 完整的分布式节点拓扑

### 2. 设计说明

✅ **架构文档**: `ARCHITECTURE.md`
- 整体架构图
- 技术栈说明
- 数据流设计

✅ **前端重设计文档**: `frontend/REDESIGN_README.md`
- 设计理念
- 组件系统
- 对比旧版改进

✅ **API 文档**: 自动生成 (FastAPI)
- 所有端点说明
- 请求/响应示例
- Schema 定义

### 3. 结果分析

#### 功能完成度

| 功能模块 | 完成度 | 备注 |
|---------|--------|------|
| 智能问答助手 | 100% | Agent 工具调用 + 知识库检索 |
| 智能化监控 | 100% | AI 分析 + 确定性规则双层保障 |
| 会话异常诊断 | 100% | 锁等待 + DN 级别诊断 |
| 慢查询诊断 | 100% | CSV 日志解析 + AI 优化建议 |
| SQL 审核 | 100% | 多级风险规则 + EXPLAIN 分析 |

#### 额外亮点

- ✨ 分布式节点逐个采集 + 失败隔离
- ✨ 双账号模式（巡检/执行分离）
- ✨ Prometheus 集成 + 告警触发巡检
- ✨ 现代化前端重设计
- ✨ 完整的修复审批工作流

#### 技术深度

- 🔥 OpenTenBase 分布式特性深度适配
- 🔥 AI Agent 工具调用实现
- 🔥 安全的权限隔离设计
- 🔥 生产级的容错机制

## 🎓 学习收获

### 技术能力

1. **分布式数据库运维**
   - OpenTenBase 架构理解（CN/DN/GTM）
   - 系统表查询和性能诊断
   - 分布式事务和锁机制

2. **AI 应用开发**
   - LLM API 集成（DeepSeek）
   - Agent 工具调用实现
   - 向量检索和 RAG
   - Prompt 工程

3. **全栈开发**
   - FastAPI 后端开发
   - Streamlit 前端开发
   - PostgreSQL 数据库
   - Docker 容器化

4. **生产级设计**
   - 权限隔离和安全设计
   - 容错和降级策略
   - 监控和告警集成
   - 操作审计和追溯

### 软技能

1. **需求分析**: 理解 AIOps 场景的真实需求
2. **架构设计**: 从零设计分布式 AIOps 系统
3. **问题解决**: 解决 OpenTenBase 兼容性问题
4. **文档编写**: 完善的技术文档和用户指南

## 🚀 未来规划

### 短期优化

1. **性能优化**
   - 巡检数据缓存
   - 批量 SQL 优化
   - 前端组件懒加载

2. **用户体验**
   - 添加数据可视化图表（Plotly）
   - 支持巡检报告导出（PDF/Excel）
   - 实现深色模式切换

3. **功能增强**
   - 支持更多诊断维度（索引建议、表膨胀）
   - 增强 SQL 审核规则库
   - 实现巡检结果对比（趋势分析）

### 长期目标

1. **智能化升级**
   - 自动化修复决策（无需人工审批）
   - 异常预测（基于历史数据）
   - 自适应巡检频率

2. **企业级功能**
   - 多租户支持
   - RBAC 权限管理
   - SSO 单点登录
   - 审计日志完整性

3. **生态集成**
   - Grafana Dashboard
   - 钉钉/企业微信告警
   - CI/CD 流水线集成

## 📞 联系方式

**开发者**: OpenTenBase AIOps 团队  
**项目地址**: `/e/opentenbase/kaiyuan_contribute/opentenbase-aiops`  
**提交日期**: 2024-11-26  
**课程**: OpenTenBase 开源贡献 - AIOps 平台方向

---

**感谢 OpenTenBase 社区和课程团队！**
