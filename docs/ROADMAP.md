# OpenTenBase AIOps - 开发路线图

**项目状态**: 🚧 **功能原型与集群兼容性验证进行中，尚未达到生产级**

**目标日期**: 2026-11-29

## 2026-11-27 当前状态

以下实测状态更新并补充前面的历史检查项：

- `scripts/verify_analyze_repair.py` 已通过真实 `lab` 集群端到端验收。巡检、AI 分析、修复提案、具名人工审批、独立非超级用户执行 `ANALYZE` 和双 DN 后置验证均成功；脚本会清理隔离表、临时角色及关联元数据，clone 后可复跑。
- 修复执行目前只验证逐 DN 表 owner 路径。OpenTenBase v5.0 上管理员 `SECURITY DEFINER` 函数调用出现 `permission denied to set session authorization opentenbase`，该路径仍未兼容。
- GitHub Actions `Regression tests` 在提交 `39e45ef` 通过，132 tests、3 skipped。AI client 改为首次 AI 请求时创建，无 DeepSeek key 时 API 的非 AI 路由和状态测试仍可加载。
- 当前集群周期巡检持续完成，最近 20 次分析耗时 P50 约 15 秒、P95 约 24 秒。实验环境样本不构成生产负载性能基线。
- 项目仍未达到生产级。代表性并发/数据规模压力测试、生产身份认证与密钥管理、部署恢复演练、更多有边界的修复操作及 `SECURITY DEFINER` 兼容路径尚未完成。

## 2026-11-24 运行状态

## 2026-11-25 交付检查

- 已实现 SQL 静态风险规则与只读 `EXPLAIN (FORMAT JSON)` API，并通过 Docker HTTP 验证危险 SQL 分类。
- Agent 已注册知识检索与锁检查只读工具。多轮工具调用中的 datetime JSON 序列化已修复并有回归测试。
- 分布式采集使用固定只读检查白名单，覆盖 CN/DN 数据库信息、连接、锁、GUC、复制等检查，节点失败独立返回。
- Docker 实机验证覆盖 1 个 CN 和 2 个 DN，三个端点的 `database_info`、`connections` 和 `locks` 检查均返回成功。
- SSE 健康审计已执行并持久化证据、AI 分析、知识引用和工具轨迹。一次完整巡检期间模型请求超时，记录正确标记了确定性 fallback。
- SQL 审核 HTTP 验收通过。Python 编译、`git diff --check` 通过，47 个 unittest 通过。
- 实验集群发现一笔跨节点 prepared transaction 阻塞等待者。审计已关联 CN 事务 ID、两个 DN 的参与事务 ID 和知识来源。该事务保持未决，系统没有自动提交或回滚。
- 由于该未决事务阻塞系统目录访问，`table_stats`、`index_usage` 和 `storage` 检查发生 lock timeout，并以部分结果和明确错误持久化。
- 修复执行仍只开放有人工审批的 `ANALYZE`。尚未在真实数据库完成执行验收，其他写操作没有执行器。

- API 容器通过 psycopg2 可连接 OpenTenBase v5.0 的 CN。
- 健康审计已持久化现场证据、AI 分析和知识引用。
- 巡检能够识别锁等待、预备事务阻塞和不可达节点。
- DN2 当前拒绝 TCP 连接，跨节点建表失败，统计视图部分超时。
- 有审批门禁的 ANALYZE 提案和执行代码已经实现，但尚未在真实集群通过执行验收。
- 首个执行操作只覆盖 ANALYZE，不能视作完整的自动运维能力。

完整 AIOps 仍需完成集群可用性基线、修复执行闭环测试、身份认证与审批审计、持续巡检/告警、更多 OpenTenBase 专项诊断和部署/恢复验证。

---

## 📊 当前进度

### ✅ 已完成（Day 1-2）

#### **1. 基础设施** 
- [x] Docker 容器化部署
- [x] 数据库连接管理
- [x] 配置系统
- [x] 日志系统
- [x] 基础数据采集（集群状态、性能指标）

#### **2. Embedding 服务**
- [x] BGE-M3 集成（SiliconFlow）
- [x] 1024 维向量生成验证
- [x] 余弦相似度计算
- [x] 批量 Embedding 支持

#### **3. 知识库系统** 🆕
- [x] 数据库 Schema 设计
- [x] 文档存储和版本管理
- [x] 文本分块（Chunking）
- [x] 向量存储（Float8[]数组）
- [x] 语义搜索（相似度检索）
- [x] 检索审计日志

**文件**: `backend/ai/knowledge_base.py`, `backend/ai/embedding_client.py`

#### **4. 诊断记忆系统** 🆕
- [x] 历史案例存储
- [x] 案例向量化
- [x] 相似案例回忆（Recall）
- [x] 有效性追踪
- [x] 案例应用记录
- [x] 自动有效性更新

**文件**: `backend/ai/diagnostic_memory.py`

#### **5. 权限与审批系统** 🆕
- [x] 三层权限模型（READ_ONLY / SAFE_WRITE / DANGEROUS）
- [x] 操作注册表
- [x] 审批工作流
- [x] 审计日志
- [x] 人工介入机制

**文件**: `backend/security/permissions.py`

#### **6. AI 诊断引擎** 🆕
- [x] 多源数据整合（集群状态 + 历史案例 + 知识库）
- [x] LLM 推理（DeepSeek）
- [x] 置信度计算
- [x] 权限感知的操作计划
- [x] 自动审批请求创建
- [x] 记忆自动保存

**文件**: `backend/engines/ai_diagnostic_engine.py`

#### **7. 数据库 Schema**
- [x] knowledge_entities (知识实体表)
- [x] knowledge_embeddings (向量表)
- [x] diagnostic_cases (诊断案例表)
- [x] case_embeddings (案例向量表)
- [x] case_applications (案例应用记录)
- [x] approval_requests (审批请求表)
- [x] operation_audit_log (审计日志表)

---

## 🚧 进行中（Day 3-4）

### **阶段一：核心功能完善**

#### 1. 知识库内容构建 📚
- [ ] 爬取 OpenTenBase 官方文档
  - GitHub Wiki
  - 官方教程
  - README 和技术文档
- [ ] 整理常见问题库
  - 社区 Issues
  - 运维经验总结
- [ ] 批量导入知识库
  - 自动分类（official_doc / troubleshooting / best_practice）
  - 版本管理
  - 来源标注

**脚本**: `scripts/build_knowledge_base.py`

**预期成果**: 50+ 文档，200+ 知识片段

#### 2. Web UI 增强 🎨
- [ ] 诊断结果展示页面
  - 根因分析卡片
  - 相似案例对比
  - 操作计划列表
  - 置信度可视化
- [ ] 审批管理界面
  - 待审批请求列表
  - 一键审批/拒绝
  - 操作详情展示
  - 风险提示
- [ ] 记忆管理界面
  - 案例库浏览
  - 有效性统计
  - 手动添加案例
  - 案例编辑/删除

**文件**: `frontend/pages/4_ai_diagnostic.py`, `frontend/pages/5_approval.py`

#### 3. API 接口完善 🔌
- [ ] FastAPI 路由
  - POST `/api/diagnostic/diagnose` - 启动诊断
  - GET `/api/diagnostic/{diagnosis_id}` - 获取结果
  - GET `/api/approval/pending` - 待审批列表
  - POST `/api/approval/{request_id}/approve` - 审批
  - GET `/api/memory/statistics` - 记忆统计
- [ ] 接口文档（Swagger）
- [ ] 错误处理和验证

**文件**: `backend/app.py`

---

## 🎯 高优先级（Day 5-6）

### **阶段二：生产级特性**

#### 1. 任务执行与恢复 🔄
- [ ] 任务执行器（Task Executor）
- [ ] 租约机制（Lease Management）
- [ ] 检查点保存（Checkpoint）
- [ ] 任务恢复（Recovery）
- [ ] 长任务支持

**设计**: 参考 AgentX 的持久化执行模型

#### 2. 操作执行引擎 ⚙️
- [ ] 安全的 SQL 执行
  - 参数化查询
  - 超时控制
  - 事务管理
- [ ] 执行结果验证
- [ ] 回滚机制
- [ ] 执行日志

#### 3. 分布式特有诊断 🌐
- [ ] 数据倾斜检测
  - 分片数据量分析
  - 热点检测
  - 重分布建议
- [ ] 跨节点查询分析
  - 网络开销识别
  - 数据移动检测
- [ ] GTM/CN 健康检查
  - 主备状态
  - 负载均衡

**文件**: `backend/engines/distributed_diagnostic.py`

#### 4. 通知系统 📧
- [ ] 审批通知（Web UI 实时刷新）
- [ ] 诊断完成通知
- [ ] 高风险操作告警
- [ ] 邮件通知（可选）

---

## 🔧 优化项（Day 7）

### **阶段三：打磨和优化**

#### 1. 性能优化
- [ ] 向量检索优化（考虑 pgvector 扩展）
- [ ] 缓存策略（LLM 响应缓存）
- [ ] 数据库索引优化
- [ ] 批量操作优化

#### 2. UI/UX 改进
- [ ] 响应式设计
- [ ] 加载动画和进度提示
- [ ] 错误提示优化
- [ ] 键盘快捷键

#### 3. 文档完善
- [ ] 部署文档
- [ ] 使用手册
- [ ] API 文档
- [ ] 架构文档
- [ ] 演示视频

#### 4. 测试
- [ ] 单元测试（核心模块）
- [ ] 集成测试（端到端）
- [ ] 压力测试（并发诊断）
- [ ] 安全测试（权限隔离）

---

## 📋 提交准备（Day 8-9）

### **最终交付物**

#### 1. 代码仓库
- [x] 完整的项目结构
- [ ] README.md（详细说明）
- [ ] ARCHITECTURE.md（架构设计）
- [ ] DEMO.md（演示说明）
- [ ] LICENSE

#### 2. 演示材料
- [ ] 演示视频（5-10分钟）
  - 功能展示
  - 诊断流程
  - AI 推理过程
  - 审批系统
- [ ] PPT/文档
  - 项目背景
  - 技术架构
  - 核心创新
  - 成果展示

#### 3. 部署包
- [ ] Docker Compose 一键启动
- [ ] 初始数据（示例知识库）
- [ ] 配置模板
- [ ] 快速开始指南

---

## 🎯 核心亮点（提交时强调）

### **技术创新**
1. ✅ **AI-Driven**: 真正的 AI 驱动，不是简单的 LLM 调用
   - 历史案例记忆系统
   - 多源数据融合推理
   - 自适应学习（有效性追踪）

2. ✅ **安全可控**: 生产级安全设计
   - 三层权限模型
   - 人工审批工作流
   - 完整审计日志
   - 操作可回滚

3. ✅ **数据库中心**: 借鉴 AgentX 设计
   - 所有状态持久化
   - 可恢复执行
   - 分布式友好

4. ✅ **分布式特性**: OpenTenBase 专有
   - 跨节点诊断
   - 分片分析
   - GTM/CN 特定检查

### **实用价值**
- 🎯 解决真实运维痛点
- 📚 可积累的知识和经验
- 🔄 持续学习和改进
- 🔒 企业级安全保障

---

## 📊 当前系统能力

### **已验证功能**
```python
# 知识库
knowledge_base.add_document(title, content, category)
results = knowledge_base.search(query, top_k=5)

# 记忆系统
case_id = memory.save_case(symptoms, root_cause, solution)
similar = memory.recall_similar_cases(symptoms, top_k=3)

# 诊断引擎
result = diagnostic_engine.diagnose(issue_description)
# 返回：
# - 根因分析
# - 解决方案（按优先级）
# - 操作计划（权限感知）
# - 相似案例
# - 置信度评估

# 审批系统
request_id = approval.request_approval(operation, params, reasoning)
approval.approve(request_id, reviewer)
```

---

## 🚀 立即行动

### **今天的任务（Day 3）**
1. ✅ 核心模块已完成
2. ⏳ 运行集成测试：`python scripts/test_ai_system.py`
3. ⏳ 构建知识库：导入官方文档
4. ⏳ 完善 Web UI：诊断页面

### **明天的任务（Day 4）**
1. 完成 Web UI
2. 实现 FastAPI 接口
3. 端到端测试
4. 开始文档编写

---

## 📞 需要决策的事项

1. **知识库来源**
   - 是否复用 AgentX 的知识库？
   - 还是独立构建 OpenTenBase 运维知识库？
   
2. **向量存储**
   - 继续用 Float8[] 数组？
   - 还是尝试安装 pgvector 扩展？

3. **LLM 模型**
   - DeepSeek API 是否稳定？
   - 是否需要备用模型（OpenAI）？

4. **部署方式**
   - Docker Compose（当前）
   - 还是提供 Kubernetes 部署？

---

**更新时间**: 2026-11-25
**负责人**: AI Development Team
**状态**: 核心架构完成，进入功能完善阶段
