# OpenTenBase AIOps - Frontend Redesign

## 🎨 设计说明

### 设计理念

本次前端重设计采用现代化、专业的企业级 AIOps 平台风格，参考了 Linear、Vercel、Tailwind UI 等优秀产品的设计语言。

### 核心改进

#### 1. **视觉设计升级**
- ✨ 现代化配色系统：清晰的视觉层次，更好的可读性
- 🎯 统一的设计语言：卡片、按钮、表单等组件风格一致
- 📱 响应式布局：适配不同屏幕尺寸
- 🌓 支持深色模式预设（通过 CSS media query）

#### 2. **信息架构优化**
- 📊 **集群总览**：快速了解集群健康状况，一目了然的指标卡片
- 🛡️ **AI 健康巡检**：流程化的巡检体验，实时进度反馈
- 📜 **巡检历史**：清晰的时间线展示，支持过滤和详情查看
- 🔍 **性能诊断**：标签页分离不同诊断维度（锁/查询/表统计）
- 🧪 **SQL 审核**：直观的风险等级展示，示例 SQL 快速填充
- 💬 **智能助手**：对话式交互，支持快速提问和工具调用展示
- 🧾 **修复中心**：清晰的审批流程，状态追踪

#### 3. **交互体验提升**
- ⚡ 快速操作按钮：关键功能一键触达
- 🔄 实时刷新：数据更新及时反馈
- 📌 快捷导航：侧边栏状态高亮，页面间跳转流畅
- 🎯 智能提示：Alert Banner 分级展示不同重要性的信息
- 💡 上下文帮助：关键位置提供说明文案

#### 4. **性能与可用性**
- 🚀 组件化设计：每个页面独立模块，易于维护
- 🎨 CSS 变量系统：统一管理颜色、间距、阴影等设计 token
- 📦 按需加载：页面内容按需渲染，减少初始加载
- ♿ 可访问性：语义化 HTML，合理的对比度

### 文件结构

```
frontend/
├── app_redesigned.py          # 主应用入口（新版）
└── pages/                     # 页面模块
    ├── __init__.py
    ├── overview.py            # 集群总览
    ├── audit.py               # AI 健康巡检
    ├── history.py             # 巡检历史
    ├── performance.py         # 性能诊断
    ├── sql_audit.py           # SQL 审核
    ├── chat.py                # 智能助手
    └── repairs.py             # 修复中心
```

### 配色系统

#### 语义化颜色
- **Primary**: `#0ea5e9` (蓝色) - 主要操作、强调内容
- **Success**: `#10b981` (绿色) - 成功状态、正常指标
- **Warning**: `#f59e0b` (琥珀色) - 警告、需要关注
- **Error**: `#ef4444` (红色) - 错误、高风险
- **Info**: `#6366f1` (靛蓝色) - 信息提示

#### 文本层次
- **Primary**: `#171717` - 主要内容
- **Secondary**: `#737373` - 次要信息
- **Tertiary**: `#a3a3a3` - 辅助说明

### 组件样式

#### 1. Alert Banner
用于重要信息提示，支持 success/warning/error/info 四种类型

```html
<div class="alert-banner success">
    <div class="alert-icon">✅</div>
    <div class="alert-content">
        <div class="alert-title">标题</div>
        <div class="alert-message">消息内容</div>
    </div>
</div>
```

#### 2. Metric Card
展示关键指标

```html
<div class="metric-card">
    <div class="metric-label">在线节点</div>
    <div class="metric-value">8/10</div>
    <div class="metric-change positive">+2 较上次</div>
</div>
```

#### 3. Node Card
节点信息卡片

```html
<div class="node-card">
    <div class="node-header">
        <div class="node-name">otb-node1</div>
        <span class="status-badge online">
            <span class="status-dot"></span>在线
        </span>
    </div>
    <div class="node-info">192.168.1.10:11003</div>
</div>
```

### 使用方法

#### 启动新版前端

```bash
# 进入项目目录
cd /e/opentenbase/kaiyuan_contribute/opentenbase-aiops

# 确保依赖已安装
pip install -r requirements.txt

# 启动新版前端
streamlit run frontend/app_redesigned.py --server.port 8088
```

#### 配置说明

新版前端复用原有的配置系统：
- 数据库连接：通过 `.env` 文件配置
- API 端点：默认 `http://aiops-api:8000`
- 支持所有原有功能模块

### 课程要求对照

| 功能模块 | 实现状态 | 页面位置 |
|---------|---------|---------|
| 智能问答助手 | ✅ 完成 | 💬 智能助手 |
| 智能化监控 | ✅ 完成 | 📊 集群总览 + 🛡️ AI 健康巡检 |
| 会话异常诊断 | ✅ 完成 | 🔍 性能诊断 - 锁分析 |
| 慢查询自动诊断 | ✅ 完成 | 🛡️ AI 健康巡检（集成） |
| SQL 审核 | ✅ 完成 | 🧪 SQL 审核 |

### 核心优势

1. **更清晰的信息层次**：通过卡片、间距、颜色区分不同重要性的信息
2. **更流畅的操作体验**：减少点击次数，关键操作一键触达
3. **更专业的视觉呈现**：符合企业级产品的审美标准
4. **更好的可维护性**：组件化设计，易于扩展和修改

### 对比旧版

| 维度 | 旧版 | 新版 |
|-----|------|------|
| 视觉风格 | 基础 Streamlit 默认样式 | 现代化企业级设计 |
| 信息密度 | 较高，拥挤 | 适中，呼吸感强 |
| 操作流程 | 分散 | 集中化、流程化 |
| 响应式 | 基本支持 | 完整适配 |
| 可维护性 | 单文件 1200+ 行 | 模块化，每个页面独立 |

### 演示截图说明

建议准备以下截图用于课程提交：

1. **集群总览页**：展示节点拓扑和健康状况
2. **AI 巡检页**：展示巡检进度和结果报告
3. **性能诊断页**：展示锁分析、长查询检测
4. **智能助手页**：展示对话式问答和工具调用
5. **SQL 审核页**：展示风险规则命中和 EXPLAIN 结果

### 后续优化建议

1. 添加数据可视化图表（使用 Plotly/ECharts）
2. 实现巡检结果导出（PDF/Excel）
3. 添加用户偏好设置（深色/浅色模式切换）
4. 实现 WebSocket 实时推送（告警通知）
5. 添加移动端优化（更好的响应式支持）

---

**设计完成时间**: 2024-11-26
**适用课程**: OpenTenBase 开源贡献 - AIOps 平台方向
