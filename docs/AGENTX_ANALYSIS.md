# OpenTenBase-AgentX 核心架构解析

## 🎯 AgentX 是什么？

**OpenTenBase-AgentX** 是一个**基于数据库的 AI Agent 管理平台**，核心理念：

> **所有 AI Agent 的状态、知识、记忆、任务、权限都存储在数据库中**  
> **数据库即真相源（Database as Source of Truth）**

---

## 🏗️ 核心架构（五层模型）

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: 用户交互层                                 │
│  - Dashboard (Web UI)                               │
│  - Portal (对话界面)                                 │
│  - API Gateway (外部 Agent 接入)                    │
└────────────┬────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────┐
│  Layer 2: AI Agent 管理层                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │Agent注册 │  │会话管理  │  │权限控制  │         │
│  │身份认证  │  │令牌刷新  │  │审计日志  │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└────────────┬────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────┐
│  Layer 3: 知识与记忆层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │知识库    │  │记忆系统  │  │向量检索  │         │
│  │(Knowledge)│  │(Memory)  │  │(Embedding)│        │
│  │- 授权检索│  │- 时态记忆│  │- 语义搜索│         │
│  │- 版本管理│  │- 工作便签│  │- 证据评估│         │
│  └──────────┘  └──────────┘  └──────────┘         │
└────────────┬────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────┐
│  Layer 4: 任务执行层                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │任务计划  │  │工具调用  │  │MCP集成   │         │
│  │(Task/Step)│  │(Action)  │  │(Protocol)│         │
│  │- 持久化  │  │- 受控执行│  │- 版本适配│         │
│  │- 可恢复  │  │- 审计    │  │- 隔离    │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└────────────┬────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────┐
│  Layer 5: 数据库层（PostgreSQL/OpenTenBase）        │
│  - 存储所有实体：Agent、任务、知识、记忆、审计      │
│  - 事务保证、权限控制、行级安全（RLS）              │
│  - 向量扩展（pg_embedding）、全文检索               │
└─────────────────────────────────────────────────────┘
```

---

## 🔑 核心设计理念

### 1. **数据库中心化**
- 所有状态都在数据库中，不依赖内存或外部存储
- 进程重启后可从数据库恢复所有状态
- 支持分布式部署（多个 worker 共享同一数据库）

### 2. **权限优先**
- **授权检索**：Agent 只能访问授权的知识
- **行级安全（RLS）**：数据库层面强制权限
- **审计日志**：所有操作都记录在数据库

### 3. **可恢复执行**
- **租约机制**：防止重复执行
- **幂等性**：同一请求多次执行结果相同
- **检查点**：长任务可以断点续传

### 4. **受控集成**
- **MCP 协议**：标准化工具调用
- **隔离执行**：工具在受控环境运行
- **版本管理**：明确的协议版本和兼容性

---

## 📚 核心模块详解

### **模块 1: Agent 注册与会话管理**

```python
# 伪代码示例
class AgentGateway:
    """外部 Agent 接入网关"""
    
    def register_agent(self, credentials):
        """注册外部 Agent"""
        # 1. 验证凭据
        # 2. 创建 Agent 实体（写入数据库）
        # 3. 绑定安全域（Domain）
        # 4. 返回令牌和实例 ID
        
    def create_session(self, agent_id, scopes):
        """创建会话"""
        # 1. 验证 Agent 身份
        # 2. 检查权限（scopes: knowledge.read, memory.write, tool.execute）
        # 3. 生成会话令牌（JWT）
        # 4. 创建租约（Lease）
        
    def heartbeat(self, instance_id):
        """会话心跳，续租"""
        # 更新租约过期时间
        
    def revoke_session(self, instance_id):
        """撤销会话"""
        # 删除租约，使所有令牌失效
```

**数据库表结构**：
```sql
-- Agent 注册表
CREATE TABLE agents (
    agent_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    registered_at TIMESTAMPTZ,
    domain_id UUID REFERENCES domains(domain_id),
    status TEXT CHECK (status IN ('active', 'suspended', 'revoked'))
);

-- 会话租约表
CREATE TABLE agent_leases (
    instance_id UUID PRIMARY KEY,
    agent_id UUID REFERENCES agents(agent_id),
    expires_at TIMESTAMPTZ NOT NULL,
    scopes TEXT[] -- ['knowledge.read', 'memory.write']
);

-- 审计日志
CREATE TABLE agent_audit_log (
    log_id BIGSERIAL PRIMARY KEY,
    agent_id UUID,
    action TEXT,
    resource TEXT,
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

---

### **模块 2: 知识库系统（Knowledge Base）**

```python
class KnowledgeManager:
    """知识库管理"""
    
    def add_knowledge(self, content, metadata, permissions):
        """添加知识"""
        # 1. 文本分块（Chunking）
        # 2. 向量化（Embedding）
        # 3. 存储到数据库（含权限标记）
        # 4. 索引更新
        
    def search(self, query, agent_id):
        """授权检索"""
        # 1. 查询向量化
        # 2. 相似度检索（仅返回 agent 有权访问的结果）
        # 3. 证据评估（充分性检查）
        # 4. 来源标注
        
    def publish_knowledge(self, draft_id, approver_id):
        """发布知识（需审核）"""
        # 从草稿转为已发布状态
```

**数据库表结构**：
```sql
-- 知识实体
CREATE TABLE knowledge_entities (
    entity_id UUID PRIMARY KEY,
    title TEXT,
    content TEXT,
    content_digest TEXT, -- SHA256 校验和
    published_at TIMESTAMPTZ,
    domain_id UUID, -- 安全域
    permissions JSONB -- 访问权限
);

-- 向量索引（使用 pgvector）
CREATE TABLE knowledge_embeddings (
    embedding_id BIGSERIAL PRIMARY KEY,
    entity_id UUID REFERENCES knowledge_entities(entity_id),
    chunk_index INT,
    embedding VECTOR(1024), -- 向量维度
    metadata JSONB
);

-- 检索日志（审计）
CREATE TABLE knowledge_retrieval_log (
    log_id BIGSERIAL PRIMARY KEY,
    agent_id UUID,
    query TEXT,
    results UUID[], -- 返回的 entity_id 列表
    timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

---

### **模块 3: 记忆系统（Memory）**

```python
class MemoryManager:
    """Agent 记忆管理"""
    
    def save_memory(self, agent_id, memory_type, content):
        """保存记忆"""
        # memory_type: 'fact' | 'procedure' | 'episodic'
        # 版本化存储（支持时间旅行）
        
    def recall(self, agent_id, context):
        """回忆（检索相关记忆）"""
        # 基于上下文的相关性检索
        
    def forget(self, agent_id, memory_id):
        """遗忘（软删除）"""
        # 标记为已删除，但保留审计记录
```

**关键特性**：
- **时态记忆**：记录时间戳，支持"X 时刻我知道什么"
- **工作便签**：任务执行过程中的临时记录
- **私有性**：每个 Agent 的记忆互相隔离

---

### **模块 4: 任务执行系统**

```python
class TaskExecutor:
    """任务执行引擎"""
    
    def create_task(self, agent_id, task_definition):
        """创建任务"""
        # 1. 解析任务定义（图结构）
        # 2. 创建 Task/Step 实体
        # 3. 返回 task_id
        
    def execute_step(self, step_id, context):
        """执行单个步骤"""
        # 1. 获取租约（防止并发执行）
        # 2. 加载上下文（知识+记忆）
        # 3. 调用 LLM 或工具
        # 4. 保存结果到数据库
        # 5. 释放租约
        
    def recover_task(self, task_id):
        """恢复中断的任务"""
        # 从数据库读取最后的检查点，继续执行
```

**租约机制**（防止重复执行）：
```sql
-- 执行租约表
CREATE TABLE execution_leases (
    step_id UUID PRIMARY KEY,
    worker_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT lease_active CHECK (expires_at > NOW())
);

-- 获取租约（原子操作）
INSERT INTO execution_leases (step_id, worker_id, acquired_at, expires_at)
VALUES ($1, $2, NOW(), NOW() + INTERVAL '5 minutes')
ON CONFLICT (step_id) DO NOTHING
RETURNING step_id; -- 如果返回空，说明租约被其他 worker 持有
```

---

### **模块 5: MCP 工具集成**

```python
class MCPAdapter:
    """MCP 协议适配器"""
    
    def list_tools(self, agent_id):
        """列出 Agent 可用的工具"""
        # 基于权限过滤
        
    def call_tool(self, agent_id, tool_name, parameters):
        """调用工具"""
        # 1. 验证权限
        # 2. 参数校验
        # 3. 在隔离环境执行
        # 4. 返回结果 + 审计日志
        
    def register_tool(self, tool_definition):
        """注册新工具"""
        # 存储工具定义到数据库
```

**关键安全措施**：
- **参数化执行**：防止注入攻击
- **超时控制**：防止长时间阻塞
- **隔离环境**：容器或沙箱运行
- **审计日志**：记录所有工具调用

---

## 🎯 AgentX 的核心价值

### **对比传统 Agent 框架**

| 特性 | 传统框架（LangChain） | OpenTenBase-AgentX |
|------|----------------------|-------------------|
| **状态存储** | 内存/文件 | 数据库（持久化） |
| **权限控制** | 应用层 | 数据库层（RLS） |
| **可恢复性** | 无 | 租约+检查点 |
| **审计** | 可选 | 强制（数据库记录） |
| **多租户** | 手动实现 | 原生支持（安全域） |
| **分布式** | 困难 | 天然支持 |

### **为什么用数据库？**

1. **ACID 事务**：保证操作的原子性
2. **并发控制**：多个 worker 协作不冲突
3. **查询能力**：SQL 查询历史、审计、统计
4. **成熟工具链**：备份、恢复、监控
5. **权限系统**：数据库原生的 RBAC + RLS

---

## 📋 总结：AgentX 做了什么

### **核心功能**
1. ✅ **Agent 生命周期管理**：注册、激活、暂停、撤销
2. ✅ **会话管理**：令牌、租约、心跳、过期处理
3. ✅ **知识库**：授权检索、版本管理、证据评估
4. ✅ **记忆系统**：时态记忆、私有隔离、版本化
5. ✅ **任务执行**：可恢复、可审计、租约保护
6. ✅ **工具集成**：MCP 协议、隔离执行、权限控制
7. ✅ **安全审计**：所有操作记录在数据库

### **设计原则**
- 📦 **数据库优先**：状态即数据库记录
- 🔒 **安全第一**：权限在数据库层强制
- 🔄 **可恢复**：任何时候都能从数据库恢复
- 📊 **可审计**：所有操作都有记录
- 🎯 **生产级**：不是 demo，是真实系统

---

## 🚀 接下来

基于 AgentX 的理念，我将为你设计：

**OpenTenBase AIOps 的 AI-Agent 架构**：
1. 如何让 AI Agent 安全地操作数据库
2. 如何实现记忆系统（历史诊断经验）
3. 如何设计可恢复的运维任务
4. 如何保证操作的安全性和审计

准备好了吗？我开始设计下一部分架构。
