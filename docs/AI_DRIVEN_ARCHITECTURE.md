# OpenTenBase AIOps - AI-Driven 架构设计

> **核心理念**：借鉴 AgentX 的数据库中心化设计，构建**可信、可审计、可恢复**的 AI 运维系统

---

## 🎯 设计目标

### **核心要求**
1. ⚠️ **安全性**：结构化修复请求有审批和专用执行器；开发模式的交互式 `execute_sql` 按数据库账号权限直接执行，生产部署必须额外隔离账号、API 认证和外部审批
2. ✅ **可审计**：所有 AI 建议和操作都有记录
3. ✅ **可恢复**：诊断任务可以中断和恢复
4. ✅ **智能化**：AI 真正能理解和诊断问题
5. ✅ **记忆系统**：学习历史诊断经验

### **与 AgentX 的对比**

| AgentX | OpenTenBase AIOps |
|--------|-------------------|
| 通用 AI Agent 平台 | 专注数据库运维 |
| 支持多种 Agent | 单一 AIOps Agent |
| 复杂的权限系统 | 简化的分级权限 |
| 企业级平台 | 轻量级工具 |

**借鉴 AgentX 的核心**：
- ✅ 数据库存储所有状态
- ✅ 记忆系统设计
- ✅ 任务可恢复机制
- ✅ 审计日志

---

## 🏗️ 整体架构

```
┌─────────────────────────────────────────────────────────┐
│  前端层 (Streamlit/React)                                │
│  - 运维看板                                              │
│  - AI 问答界面                                           │
│  - 诊断任务管理                                          │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│  业务逻辑层 (FastAPI)                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │诊断引擎  │  │任务管理  │  │记忆管理  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│  AI Agent 层                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │数据采集  │  │AI推理    │  │工具执行  │             │
│  │Agent     │  │Agent     │  │Agent     │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────────────┐
│  数据存储层                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │OpenTenBase│  │AIOps     │  │向量库   │             │
│  │(监控目标) │  │元数据DB  │  │(记忆)   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└─────────────────────────────────────────────────────────┘
```

---

## 📊 核心模块设计

### **模块 1: 三层权限模型**

借鉴 AgentX 的安全设计，但简化为运维场景：

```python
# backend/security/permissions.py
class PermissionLevel(Enum):
    """操作权限等级"""
    READ_ONLY = "read_only"      # 只读：查询、分析
    SAFE_WRITE = "safe_write"    # 安全写：创建索引、ANALYZE
    DANGEROUS = "dangerous"       # 危险：删除数据、重启服务

class OperationRegistry:
    """操作注册表"""
    
    OPERATIONS = {
        # 只读操作（AI 可以自动执行）
        "query_cluster_status": PermissionLevel.READ_ONLY,
        "explain_query": PermissionLevel.READ_ONLY,
        "check_locks": PermissionLevel.READ_ONLY,
        
        # 安全写操作（AI 可以建议，需要人工确认）
        "create_index": PermissionLevel.SAFE_WRITE,
        "analyze_table": PermissionLevel.SAFE_WRITE,
        "vacuum_table": PermissionLevel.SAFE_WRITE,
        
        # 危险操作（AI 只能建议，严格审批）
        "kill_query": PermissionLevel.DANGEROUS,
        "drop_table": PermissionLevel.DANGEROUS,
        "restart_service": PermissionLevel.DANGEROUS,
    }
    
    @classmethod
    def require_approval(cls, operation: str) -> bool:
        """是否需要人工审批"""
        level = cls.OPERATIONS.get(operation)
        return level in [PermissionLevel.SAFE_WRITE, PermissionLevel.DANGEROUS]
```

**审批流程**：
```python
class ApprovalWorkflow:
    """审批工作流"""
    
    def request_approval(self, operation: str, parameters: dict, ai_reasoning: str):
        """AI 请求执行操作"""
        # 1. 创建审批请求（写入数据库）
        approval_request = {
            'request_id': uuid.uuid4(),
            'operation': operation,
            'parameters': parameters,
            'ai_reasoning': ai_reasoning,  # AI 的推理过程
            'risk_level': OperationRegistry.OPERATIONS[operation].value,
            'status': 'pending',
            'created_at': datetime.now()
        }
        
        # 2. 存储到数据库
        self.db.save_approval_request(approval_request)
        
        # 3. 通知管理员（Web UI、邮件、Slack）
        self.notify_admin(approval_request)
        
        return approval_request['request_id']
    
    def approve(self, request_id: str, approver: str):
        """人工审批"""
        # 1. 更新审批状态
        self.db.update_approval_status(request_id, 'approved', approver)
        
        # 2. 执行操作
        request = self.db.get_approval_request(request_id)
        result = self.execute_safe(request['operation'], request['parameters'])
        
        # 3. 记录审计日志
        self.audit_log(request_id, approver, result)
        
        return result
```

---

### **模块 2: 记忆系统（历史诊断经验）**

借鉴 AgentX 的记忆设计，存储历史诊断案例：

```python
# backend/ai/memory_system.py
class DiagnosticMemory:
    """诊断记忆系统"""
    
    def __init__(self, vector_store, db):
        self.vector_store = vector_store  # Chroma/pgvector
        self.db = db  # OpenTenBase
    
    def save_diagnostic_case(self, case: dict):
        """保存诊断案例"""
        # case = {
        #     'symptoms': '主从延迟突增',
        #     'metrics': {'replication_lag': 15, 'cpu_usage': 85},
        #     'root_cause': '从库磁盘 IO 饱和',
        #     'solution': 'VACUUM + 扩容磁盘',
        #     'effectiveness': 0.9  # 解决方案有效性（0-1）
        # }
        
        # 1. 向量化（用于相似案例检索）
        case_embedding = self.vectorize(case['symptoms'] + case['root_cause'])
        
        # 2. 存储到向量库
        self.vector_store.add(
            id=case['case_id'],
            embedding=case_embedding,
            metadata=case
        )
        
        # 3. 存储到数据库（结构化数据）
        self.db.execute("""
            INSERT INTO diagnostic_cases 
            (case_id, symptoms, root_cause, solution, effectiveness, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (case['case_id'], case['symptoms'], case['root_cause'], 
              case['solution'], case['effectiveness']))
    
    def recall_similar_cases(self, current_symptoms: str, top_k=5):
        """回忆相似案例"""
        # 1. 向量检索
        query_embedding = self.vectorize(current_symptoms)
        similar_cases = self.vector_store.search(query_embedding, top_k=top_k)
        
        # 2. 按有效性排序
        similar_cases.sort(key=lambda x: x['effectiveness'], reverse=True)
        
        return similar_cases
    
    def update_effectiveness(self, case_id: str, new_score: float):
        """更新案例有效性（用户反馈）"""
        self.db.execute("""
            UPDATE diagnostic_cases 
            SET effectiveness = %s, updated_at = NOW()
            WHERE case_id = %s
        """, (new_score, case_id))
```

**数据库表结构**：
```sql
-- 诊断案例表
CREATE TABLE diagnostic_cases (
    case_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symptoms TEXT NOT NULL,
    metrics JSONB,  -- 诊断时的指标快照
    root_cause TEXT NOT NULL,
    solution TEXT NOT NULL,
    effectiveness FLOAT CHECK (effectiveness BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    tags TEXT[]  -- ['replication', 'performance', 'lock']
);

-- 案例应用记录（用于统计哪些案例最有用）
CREATE TABLE case_applications (
    application_id BIGSERIAL PRIMARY KEY,
    case_id UUID REFERENCES diagnostic_cases(case_id),
    applied_at TIMESTAMPTZ DEFAULT NOW(),
    outcome TEXT,  -- 'solved' | 'partially_solved' | 'not_solved'
    user_id TEXT
);
```

---

### **模块 3: AI 诊断引擎（增强版）**

结合记忆系统和 LLM 推理：

```python
# backend/engines/ai_diagnostic_engine.py
class AIDiagnosticEngine:
    """AI 诊断引擎"""
    
    def __init__(self, llm_client, memory_system, data_collector):
        self.llm = llm_client
        self.memory = memory_system
        self.collector = data_collector
    
    def diagnose(self, issue_description: str):
        """完整的诊断流程"""
        
        # Step 1: 收集当前状态
        current_state = self.collector.collect_all()
        
        # Step 2: 回忆相似案例
        similar_cases = self.memory.recall_similar_cases(issue_description)
        
        # Step 3: 构建 AI Prompt
        prompt = self._build_diagnostic_prompt(
            issue=issue_description,
            current_state=current_state,
            similar_cases=similar_cases
        )
        
        # Step 4: LLM 推理
        ai_analysis = self.llm.chat([
            {"role": "system", "content": DIAGNOSTIC_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ])
        
        # Step 5: 解析 AI 输出
        diagnosis = self._parse_ai_output(ai_analysis)
        
        # Step 6: 生成可执行的操作计划
        action_plan = self._generate_action_plan(diagnosis)
        
        # Step 7: 保存诊断记录
        self._save_diagnostic_session(issue_description, diagnosis, action_plan)
        
        return {
            'diagnosis': diagnosis,
            'action_plan': action_plan,
            'similar_cases': similar_cases,
            'confidence': diagnosis.get('confidence', 0.0)
        }
    
    def _build_diagnostic_prompt(self, issue, current_state, similar_cases):
        """构建诊断 Prompt"""
        return f"""
# 数据库诊断任务

## 当前问题
{issue}

## 集群当前状态
- 节点数：{len(current_state['nodes'])}
- 连接数：{current_state['connections']['total']}/{current_state['connections']['max']}
- 主从延迟：{current_state.get('replication_lag', 'N/A')}
- 锁等待：{len(current_state.get('locks', []))} 个

## 历史相似案例
{self._format_cases(similar_cases)}

## 任务要求
1. 分析根本原因
2. 评估风险等级（low/medium/high/critical）
3. 提出解决方案（按优先级排序）
4. 给出可执行的 SQL/命令（如果适用）

## 输出格式（JSON）
{{
    "root_cause": "...",
    "risk_level": "...",
    "solutions": [
        {{
            "priority": 1,
            "description": "...",
            "commands": ["SQL或命令"],
            "risk": "...",
            "expected_outcome": "..."
        }}
    ],
    "confidence": 0.85,
    "reasoning": "推理过程..."
}}
"""
    
    def _generate_action_plan(self, diagnosis):
        """生成可执行的操作计划"""
        action_plan = []
        
        for solution in diagnosis.get('solutions', []):
            for command in solution.get('commands', []):
                # 检查操作权限
                operation = self._identify_operation(command)
                requires_approval = OperationRegistry.require_approval(operation)
                
                action = {
                    'action_id': uuid.uuid4(),
                    'operation': operation,
                    'command': command,
                    'description': solution['description'],
                    'risk': solution['risk'],
                    'requires_approval': requires_approval,
                    'status': 'pending_approval' if requires_approval else 'ready'
                }
                
                action_plan.append(action)
        
        return action_plan
```

**Prompt 模板**：
```python
DIAGNOSTIC_SYSTEM_PROMPT = """你是 OpenTenBase 分布式数据库的专家 DBA。

你的诊断原则：
1. 数据驱动：基于实际指标和日志，不要猜测
2. 安全优先：推荐的操作必须是可逆的或低风险的
3. 分布式优先：考虑 OpenTenBase 的分布式特性（GTM、CN、DN）
4. 学习历史：参考历史相似案例的解决方案
5. 可验证：给出验证问题是否解决的方法

你的输出必须：
- 结构化（JSON 格式）
- 包含推理过程
- 给出可执行的命令
- 评估每个方案的风险
- 说明预期效果
"""
```

---

### **模块 4: 任务执行与恢复**

借鉴 AgentX 的租约机制，实现可恢复的诊断任务：

```python
# backend/engines/task_executor.py
class DiagnosticTaskExecutor:
    """诊断任务执行器"""
    
    def create_task(self, task_definition: dict):
        """创建诊断任务"""
        task = {
            'task_id': uuid.uuid4(),
            'type': task_definition['type'],  # 'one-time' | 'periodic'
            'steps': task_definition['steps'],
            'status': 'pending',
            'created_at': datetime.now()
        }
        
        # 存储到数据库
        self.db.execute("""
            INSERT INTO diagnostic_tasks 
            (task_id, type, steps, status, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (task['task_id'], task['type'], json.dumps(task['steps']), 
              task['status'], task['created_at']))
        
        return task['task_id']
    
    def execute_task(self, task_id: str):
        """执行任务（可恢复）"""
        # 1. 获取租约（防止并发执行）
        if not self._acquire_lease(task_id):
            raise RuntimeError("Task already running")
        
        try:
            # 2. 加载任务
            task = self._load_task(task_id)
            
            # 3. 找到最后的检查点
            last_checkpoint = self._get_last_checkpoint(task_id)
            start_step = last_checkpoint['step_index'] + 1 if last_checkpoint else 0
            
            # 4. 执行步骤
            for i, step in enumerate(task['steps'][start_step:], start=start_step):
                result = self._execute_step(step)
                
                # 5. 保存检查点
                self._save_checkpoint(task_id, i, result)
                
                # 6. 更新任务状态
                self.db.execute("""
                    UPDATE diagnostic_tasks 
                    SET current_step = %s, updated_at = NOW()
                    WHERE task_id = %s
                """, (i, task_id))
            
            # 7. 任务完成
            self.db.execute("""
                UPDATE diagnostic_tasks 
                SET status = 'completed', completed_at = NOW()
                WHERE task_id = %s
            """, (task_id,))
            
        finally:
            # 8. 释放租约
            self._release_lease(task_id)
    
    def _acquire_lease(self, task_id: str, timeout=300):
        """获取任务租约"""
        try:
            self.db.execute("""
                INSERT INTO task_leases (task_id, worker_id, acquired_at, expires_at)
                VALUES (%s, %s, NOW(), NOW() + INTERVAL '%s seconds')
                ON CONFLICT (task_id) DO NOTHING
            """, (task_id, os.getpid(), timeout))
            
            # 检查是否成功获取
            result = self.db.query("""
                SELECT worker_id FROM task_leases WHERE task_id = %s
            """, (task_id,))
            
            return result[0]['worker_id'] == os.getpid()
        except Exception as e:
            logger.error(f"Failed to acquire lease: {e}")
            return False
```

**数据库表结构**：
```sql
-- 诊断任务表
CREATE TABLE diagnostic_tasks (
    task_id UUID PRIMARY KEY,
    type TEXT NOT NULL,
    steps JSONB NOT NULL,
    status TEXT NOT NULL,  -- 'pending' | 'running' | 'completed' | 'failed'
    current_step INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- 任务租约表（防止并发执行）
CREATE TABLE task_leases (
    task_id UUID PRIMARY KEY REFERENCES diagnostic_tasks(task_id),
    worker_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT lease_valid CHECK (expires_at > NOW())
);

-- 任务检查点表（用于恢复）
CREATE TABLE task_checkpoints (
    checkpoint_id BIGSERIAL PRIMARY KEY,
    task_id UUID REFERENCES diagnostic_tasks(task_id),
    step_index INT NOT NULL,
    step_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 🎯 完整流程示例

### **场景：主从延迟诊断**

```
1. 用户输入：
   "主从延迟突然增加到 15 秒"

2. 系统自动执行：
   ├─ 数据采集 Agent 收集：
   │  ├─ pg_stat_replication
   │  ├─ 从库 CPU/IO 指标
   │  └─ 网络延迟
   │
   ├─ 记忆系统检索：
   │  └─ 找到 3 个相似案例
   │
   ├─ AI 推理 Agent 分析：
   │  ├─ 根因：从库磁盘 IO 饱和（85% iowait）
   │  ├─ 风险等级：HIGH
   │  └─ 解决方案：
   │     1. [SAFE_WRITE] VACUUM 清理膨胀
   │     2. [DANGEROUS] 临时降低从库负载
   │
   └─ 操作计划生成：
      ├─ Action 1: VACUUM (需审批)
      └─ Action 2: 监控效果 (自动执行)

3. 展示给用户：
   ┌─────────────────────────────────────┐
   │ 🔍 诊断结果                          │
   ├─────────────────────────────────────┤
   │ 根本原因：                           │
   │   从库磁盘 IO 饱和 (85% iowait)     │
   │                                      │
   │ 风险等级：🔴 HIGH                    │
   │                                      │
   │ 解决方案：                           │
   │ ┌─ 方案 1 (优先级: 高) ────────┐   │
   │ │ 执行 VACUUM 清理表膨胀        │   │
   │ │ 命令: VACUUM ANALYZE orders;  │   │
   │ │ [审批并执行] [查看详情]       │   │
   │ └───────────────────────────────┘   │
   │                                      │
   │ 📚 参考案例：                        │
   │   - 案例 #42: 相似度 92%             │
   │     (有效性: 0.89)                   │
   └─────────────────────────────────────┘

4. 用户点击 [审批并执行]：
   ├─ 系统创建审批请求
   ├─ DBA 在审批界面确认
   ├─ 系统执行 VACUUM
   ├─ 记录审计日志
   └─ 保存为新的诊断案例

5. 后续：
   ├─ 监控延迟是否恢复
   ├─ 用户反馈有效性
   └─ 更新记忆系统
```

---

## 📋 下一步计划

基于这个架构，我可以立即开始实现：

### **阶段一（核心）**
1. ✅ 权限系统和审批流程
2. ✅ 记忆系统（向量库 + 数据库）
3. ✅ AI 诊断引擎（增强版）

### **阶段二（高级）**
4. ✅ 任务执行器（可恢复）
5. ✅ 审计日志系统
6. ✅ Web UI 升级

你想让我先实现哪个模块？
