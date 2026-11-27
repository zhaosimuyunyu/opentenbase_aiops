"""OpenTenBase AIOps - Main Streamlit Application"""
import streamlit as st
import sys
import os
from api_client import requests
import json
import html
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.utils.logger import setup_logger
from backend.collectors.cluster import ClusterCollector
from backend.collectors.performance import PerformanceCollector
from backend.ai.llm_client import DeepSeekClient
from backend.engines.repair_workflow import has_repair_identity

logger = setup_logger(__name__)

# Page configuration
st.set_page_config(
    page_title="OpenTenBase AIOps",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)
from auth import require_ui_auth
require_ui_auth(st)

# Product workspace theme
st.markdown("""
<style>
    :root {
        --canvas: #f3f6f8;
        --surface: #ffffff;
        --ink: #1d2a35;
        --muted: #697985;
        --line: #dce5e8;
        --teal: #087e78;
        --blue: #2872b8;
        --amber: #b66b12;
        --red: #bd4f48;
        --green: #31815d;
    }
    html, body, [data-testid="stAppViewContainer"] { background: var(--canvas); color: var(--ink); }
    [data-testid="stHeader"] { background: rgba(243,246,248,.92); }
    [data-testid="stToolbar"] { right: 1rem; }
    .main .block-container { max-width: 1660px; padding: 1.45rem 2.2rem 3rem; }
    [data-testid="stSidebar"] { background: #17262d; border-right: 1px solid #263941; }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1.2rem; }
    [data-testid="stSidebar"] * { color: #e7eff0; }
    [data-testid="stSidebar"] hr { border-color: #34464c; margin: 1rem 0; }
    [data-testid="stSidebar"] [data-testid="stRadio"] > label { display: none; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .18rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        padding: .52rem .62rem; border-radius: 6px; transition: background .12s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background: #243941; }
    [data-testid="stSidebar"] [role="radiogroup"] label p { font-size: .91rem; }
    .brand-lockup { display:flex; align-items:center; gap:.72rem; padding:.25rem .25rem .85rem; }
    .brand-mark { width:2.4rem; height:2.4rem; display:grid; place-items:center; border-radius:6px; background:#0b7975; color:#fff; font-weight:750; font-size:.84rem; }
    .brand-name { color:#f4f8f8; font-size:1.05rem; font-weight:680; line-height:1.15; }
    .brand-subtitle { color:#9eb0b5; font-size:.74rem; margin-top:.18rem; }
    .nav-caption { color:#91a4aa; font-size:.68rem; letter-spacing:.08em; text-transform:uppercase; font-weight:700; margin:.7rem .25rem .1rem; }
    .workspace-header { display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; border-bottom:1px solid var(--line); padding:.15rem 0 1.05rem; margin-bottom:1.2rem; }
    .workspace-kicker { color:var(--teal); font-size:.69rem; font-weight:750; letter-spacing:.08em; text-transform:uppercase; margin-bottom:.28rem; }
    .workspace-title { font-size:1.56rem; color:var(--ink); font-weight:720; line-height:1.18; }
    .workspace-subtitle { color:var(--muted); font-size:.88rem; margin-top:.35rem; }
    .workspace-context { text-align:right; color:var(--muted); font-size:.78rem; padding-top:.2rem; white-space:nowrap; }
    .context-dot { display:inline-block; width:.48rem; height:.48rem; border-radius:50%; background:#3e9a70; margin-right:.4rem; }
    .section-heading { display:flex; align-items:baseline; justify-content:space-between; gap:1rem; margin:.45rem 0 .7rem; }
    .section-heading h3 { font-size:1rem; font-weight:700; color:var(--ink); margin:0; }
    .section-note { color:var(--muted); font-size:.77rem; }
    .overview-status { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.78rem 1rem; border:1px solid #b9d9cc; border-left:4px solid var(--green); background:#edf7f1; border-radius:6px; margin:.1rem 0 1rem; }
    .overview-status.partial { border-color:#ead3a5; border-left-color:var(--amber); background:#fff8e9; }
    .overview-status.error { border-color:#e8c1be; border-left-color:var(--red); background:#fff1ef; }
    .status-title { color:var(--ink); font-weight:700; font-size:.88rem; }
    .status-detail { color:var(--muted); font-size:.78rem; margin-top:.15rem; }
    .status-time { color:var(--muted); font-size:.74rem; white-space:nowrap; }
    .node-card { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:.78rem .84rem; min-height:102px; }
    .node-card-top { display:flex; align-items:center; justify-content:space-between; gap:.4rem; }
    .node-name { color:var(--ink); font-weight:720; font-size:.91rem; }
    .node-role { color:var(--muted); font-size:.72rem; margin-top:.28rem; }
    .node-endpoint { color:#4d606c; font-size:.75rem; margin-top:.48rem; font-family:ui-monospace, SFMono-Regular, Consolas, monospace; }
    .node-state { border-radius:999px; padding:.14rem .42rem; font-size:.68rem; font-weight:700; }
    .node-state.online { background:#e7f4ec; color:#2c7954; }
    .node-state.offline { background:#fae9e7; color:#a63e38; }
    .node-state.unknown { background:#edf1f3; color:#687985; }
    .finding-row { padding:.72rem 0; border-bottom:1px solid var(--line); }
    .finding-row:last-child { border-bottom:0; }
    .finding-top { display:flex; align-items:center; justify-content:space-between; gap:.6rem; }
    .finding-name { color:var(--ink); font-size:.84rem; font-weight:680; }
    .finding-severity { font-size:.67rem; font-weight:750; text-transform:uppercase; }
    .finding-severity.high, .finding-severity.critical { color:var(--red); }
    .finding-severity.medium { color:var(--amber); }
    .finding-severity.low { color:var(--blue); }
    .finding-description { color:var(--muted); font-size:.77rem; line-height:1.45; margin-top:.25rem; }
    [data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:.75rem .9rem; }
    [data-testid="stMetricLabel"] { color:var(--muted); font-size:.77rem; }
    [data-testid="stMetricValue"] { color:var(--ink); font-size:1.5rem; font-weight:720; }
    [data-testid="stMetricDelta"] { font-size:.72rem; }
    div.stButton > button { border-radius:6px; min-height:2.45rem; font-weight:650; }
    div.stButton > button[kind="primary"] { background:#087e78; border-color:#087e78; color:#fff; }
    div.stButton > button[kind="primary"]:hover { background:#066b66; border-color:#066b66; }
    [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:6px; overflow:hidden; }
    [data-testid="stExpander"] { border-color:var(--line); border-radius:6px; }
    [data-testid="stAlert"] { border-radius:6px; }
    .main-header { display:none; }
    @media (max-width: 900px) {
        .main .block-container { padding:1rem 1rem 2rem; }
        .workspace-header { flex-direction:column; }
        .workspace-context { text-align:left; }
        .node-card { min-height:88px; }
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'config' not in st.session_state:
    st.session_state.config = Config()

if 'db_connector' not in st.session_state:
    st.session_state.db_connector = OpenTenBaseConnector(st.session_state.config)

if 'llm_client' not in st.session_state:
    try:
        st.session_state.llm_client = DeepSeekClient(st.session_state.config)
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        st.session_state.llm_client = None

# Sidebar navigation
with st.sidebar:
    st.markdown(
        '<div class="brand-lockup"><div class="brand-mark">OTB</div>'
        '<div><div class="brand-name">OpenTenBase</div>'
        '<div class="brand-subtitle">智能运维工作台</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="nav-caption">监控与诊断</div>', unsafe_allow_html=True)
    navigation = {
        "📊 集群总览": "📊 健康监控",
        "🛡️ AI 巡检": "🛡️ 只读巡检",
        "📜 巡检记录": "📜 巡检历史",
        "🔍 性能诊断": "🔍 性能诊断",
        "🧪 SQL 审核": "🧪 SQL 审核",
        "💬 Agent 助手": "💬 智能问答",
        "🧾 处置中心": "🧾 修复审批",
    }
    selected_navigation = st.radio(
        "工作区", list(navigation), label_visibility="collapsed", key="navigation_page"
    )
    page = navigation[selected_navigation]
    st.markdown('<div class="nav-caption">数据库连接</div>', unsafe_allow_html=True)

    if st.button("测试连接", use_container_width=True):
        with st.spinner("连接中..."):
            status = st.session_state.db_connector.test_connection()

            if status['connected']:
                st.success("✅ 已连接")
                st.caption(f"数据库: {status.get('database', 'unknown')}")
                st.caption(f"用户: {status.get('user', 'unknown')}")
            else:
                st.error("❌ 连接失败")
                st.caption(f"错误: {status.get('error', 'unknown')}")

    st.markdown("---")
    st.caption(f"{st.session_state.config.DB_HOST}:{st.session_state.config.DB_PORT}")
    st.caption(f"{st.session_state.config.DB_NAME} · {st.session_state.config.DB_USER}")
    st.caption(f"AI · {st.session_state.config.DEEPSEEK_MODEL}")


PAGE_META = {
    "📊 健康监控": ("集群总览", "拓扑、连接容量、复制链路与最近一次巡检结果"),
    "🛡️ 只读巡检": ("AI 巡检", "采集 OpenTenBase 实时证据，生成可追溯的诊断记录"),
    "📜 巡检历史": ("巡检记录", "查询历史审计、风险发现和诊断依据"),
    "🧾 修复审批": ("处置中心", "复核待处理建议，查看执行状态与验证结果"),
    "💬 智能问答": ("Agent 助手", "结合实时数据库工具与 OpenTenBase 知识库分析问题"),
    "🔍 性能诊断": ("性能诊断", "检查锁等待、长查询与数据节点表统计"),
    "🧪 SQL 审核": ("SQL 审核", "评估语句风险并查看只读执行计划"),
}


def navigate_to_page(page_name):
    st.session_state["navigation_page"] = page_name


def load_sql_template(query):
    st.session_state["sql_review_editor"] = query


def set_chat_prompt(prompt):
    st.session_state["agent_chat_input"] = prompt


page_title, page_subtitle = PAGE_META[page]
header_left, header_right = st.columns([5, 2])
with header_left:
    st.markdown(
        f'<div class="workspace-header"><div><div class="workspace-kicker">OPENTENBASE / AIOPS</div>'
        f'<div class="workspace-title">{html.escape(page_title)}</div>'
        f'<div class="workspace-subtitle">{html.escape(page_subtitle)}</div></div></div>',
        unsafe_allow_html=True,
    )
with header_right:
    st.markdown(
        f'<div class="workspace-context"><span class="context-dot"></span>'
        f'{html.escape(st.session_state.config.DB_HOST)}:{st.session_state.config.DB_PORT}'
        f'<br>{html.escape(st.session_state.config.DB_NAME)}</div>',
        unsafe_allow_html=True,
    )

def render_analysis_status(analysis):
    if not isinstance(analysis, dict):
        return
    tool_errors = set(analysis.get("tool_errors") or [])
    tool_trace = analysis.get("tool_trace") or []
    if tool_trace:
        st.caption("诊断工具调用")
        st.dataframe(tool_trace, hide_index=True, use_container_width=True)
    if "KnowledgeToolCallLimit" in tool_errors:
        st.warning("已达到本次巡检的知识检索次数上限")
        tool_errors.remove("KnowledgeToolCallLimit")
    if tool_errors:
        st.warning(f"模型发起的知识检索失败（{' · '.join(sorted(tool_errors))}）")
    retrieval_error = analysis.get("fallback_knowledge_error")
    if retrieval_error:
        details = retrieval_error["type"]
        if retrieval_error.get("sqlstate"):
            details += f" · SQLSTATE {retrieval_error['sqlstate']}"
        st.warning(f"补充知识检索失败（{details}）")
    source = (analysis.get("structured") or {}).get("analysis_source")
    if source == "collection_failure":
        st.info("采集失败，未运行模型诊断")
    elif source == "model":
        st.caption("诊断来源 · 模型")
    elif analysis.get("analysis_fallback"):
        details = []
        if analysis.get("ai_http_status"):
            details.append(f"HTTP {analysis['ai_http_status']}")
        if analysis.get("ai_error"):
            details.append(analysis["ai_error"])
        suffix = f"（{' · '.join(details)}）" if details else ""
        message = "模型诊断失败，已使用巡检规则" if source == "deterministic_evidence_rules" else "模型诊断未生成可用报告"
        st.warning(message + suffix)


def render_reanalysis_button(api_base, audit_id, analysis, key_prefix):
    if not isinstance(analysis, dict) or not analysis.get("analysis_fallback"):
        return None
    if not st.button("重试 AI 分析", key=f"{key_prefix}-{audit_id}"):
        return None
    try:
        response = requests.post(
            f"{api_base}/api/audits/{audit_id}/reanalyze",
            timeout=st.session_state.config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        st.success("已使用已保存的审计证据重新分析")
        return response.json()
    except requests.RequestException as error:
        st.error(f"重新分析失败: {error}")
        return None


def render_collection_status(evidence):
    diagnostics = (evidence.get("cluster") or {}).get("pg_clean_diagnostics") or []
    if diagnostics and any(
        finding.get("check") == "prepared_transaction_blocker"
        for finding in evidence.get("findings", [])
    ):
        diagnostic = diagnostics[0]
        if not diagnostic.get("registered"):
            message = "当前库未注册 pg_clean 诊断函数"
            if diagnostic.get("package_available") is False:
                message += "，服务端缺少扩展安装包"
            if diagnostic.get("launcher_setting") == "on":
                message += "。后台清理器已启用"
            st.warning(message)
        elif diagnostic.get("executable") is False:
            st.warning("巡检账号缺少 pg_clean 诊断函数的执行权限")
        elif diagnostic.get("executable") is True:
            st.caption("pg_clean 诊断入口已注册，巡检账号具有执行权限")
    errors = evidence.get("collection_errors") or {}
    status = evidence.get("collection_status")
    if not errors and status not in {"partial", "error"}:
        return
    if status == "error":
        st.error("巡检采集失败")
    else:
        st.warning("巡检只获得部分数据")
    if errors:
        st.dataframe(
            [
                {
                    "检查项": name, "错误类型": error.get("type"),
                    "SQLSTATE": error.get("sqlstate"), "详情": error.get("message"),
                }
                for name, error in errors.items()
            ],
            use_container_width=True,
            hide_index=True,
        )
    fallback = (evidence.get("performance") or {}).get("data_node_stats_fallback") or {}
    if fallback:
        st.write("目标表补充统计")
        st.dataframe(
            [
                {
                    "目标表": target,
                    "已采集节点": ", ".join(
                        node["node_name"] for table in result["tables"] for node in table["nodes"]
                    ),
                    "采集错误": ", ".join(result["errors"]),
                }
                for target, result in fallback.items()
            ],
            use_container_width=True,
            hide_index=True,
        )
    if not evidence.get("statistics_target") and any(
        error.get("sqlstate") == "55P03" and (
            name in {"table_stats", "index_usage"} or name.startswith("data_node_stats:")
        )
        for name, error in errors.items()
    ):
        st.info("全库统计遇到锁等待。可在「只读巡检」中填写目标表，单独复查该表的 DN 统计。")


def render_automatic_repair(evidence):
    outcome = evidence.get("automatic_repair")
    if not outcome:
        return
    status = outcome.get("status")
    labels = {
        "executed": "自动修复已执行并通过复核",
        "failed": "自动修复执行失败",
        "unverified": "自动修复执行后未通过复核",
        "skipped": "自动修复未执行",
        "error": "自动修复流程发生错误",
    }
    label = labels.get(status, "自动修复状态")
    reason = outcome.get("reason")
    if status == "executed":
        st.success(label)
    elif status in {"failed", "unverified", "error"}:
        st.error(label)
    else:
        st.info(label)
    if reason:
        st.caption(f"原因：{reason}")
    if outcome.get("request_id"):
        st.caption(f"修复请求 ID：{outcome['request_id']}")
    result = outcome.get("result") or {}
    postcondition = result.get("postcondition") or {}
    if postcondition:
        st.caption(
            f"逐 DN 复核：{'通过' if postcondition.get('verified') else '未通过'} · "
            f"已更新节点 {', '.join(postcondition.get('advanced_nodes') or []) or '无'}"
        )
    with st.expander("自动修复决策与执行详情"):
        st.json(outcome)


def render_repair_proposal(api_base, audit_id, findings):
    candidates = [index for index, item in enumerate(findings) if item.get("check") == "stale_table_statistics"]
    eligible = [index for index in candidates if has_repair_identity(findings[index].get("evidence") or {})]
    if len(eligible) < len(candidates):
        st.warning("部分发现缺少数据库或表身份，请重新巡检后创建提案。")
    if eligible:
        selected_finding = st.selectbox(
            "生成统计维护提案",
            eligible,
            format_func=lambda index: findings[index]["observed"],
            key=f"repair-finding-{audit_id}",
        )
        repair_reason = st.text_input(
            "提案说明", value="审计发现自上次分析以来有大量行变更，建议刷新优化器统计。",
            key=f"repair-reason-{audit_id}",
        )
        if st.button("创建待审批 ANALYZE 提案", key=f"create-repair-{audit_id}"):
            response = requests.post(
                f"{api_base}/api/audits/{audit_id}/repair-requests",
                json={"finding_index": selected_finding, "reason": repair_reason},
                timeout=st.session_state.config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS,
            )
            if response.ok:
                proposal = response.json()
                if proposal.get("reused"):
                    st.info(f"已有提案 {proposal['request_id']} · {proposal['status']}")
                else:
                    st.success(f"待审批请求已创建: {proposal['request_id']}")
            else:
                st.error(response.text)

    lock_candidates = []
    for finding_index, finding in enumerate(findings):
        if finding.get("check") != "data_node_lock_waits":
            continue
        evidence = finding.get("evidence") or {}
        for waiting_lock in evidence.get("waits") or []:
            for blocker in waiting_lock.get("blockers") or []:
                if all(blocker.get(key) for key in (
                    "node_name", "pid", "database", "usename", "query_start", "query",
                )) and evidence.get("database_identity", {}).get("system_identifier"):
                    parameters = {
                        key: blocker.get(key) for key in (
                            "node_name", "pid", "database", "application_name",
                            "query_start", "xact_start", "query",
                        )
                    }
                    parameters["user"] = blocker.get("usename")
                    parameters["database_identity"] = evidence["database_identity"]
                    lock_candidates.append((finding_index, blocker, parameters))
    if lock_candidates:
        selected = st.selectbox(
            "生成阻塞查询处置建议",
            range(len(lock_candidates)),
            format_func=lambda index: (
                f"{lock_candidates[index][1]['node_name']} · PID "
                f"{lock_candidates[index][1]['pid']} · {lock_candidates[index][1]['database']} · "
                f"{lock_candidates[index][1]['query'][:100]}"
            ),
            key=f"cancel-query-finding-{audit_id}",
        )
        finding_index, blocker, parameters = lock_candidates[selected]
        st.info("取消查询属于高风险操作。当前仅创建人工审核建议，执行器尚未通过分布式身份与权限验证。")
        reason = st.text_input(
            "处置原因", value="该会话在数据节点持有锁并阻塞其他事务。",
            key=f"cancel-query-reason-{audit_id}",
        )
        if st.button("创建取消查询审核建议", key=f"create-cancel-query-{audit_id}"):
            response = requests.post(
                f"{api_base}/api/audits/{audit_id}/repair-requests",
                json={
                    "finding_index": finding_index, "reason": reason,
                    "operation": "cancel_query", "parameters": parameters,
                },
                timeout=st.session_state.config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS,
            )
            if response.ok:
                st.success(f"审核建议已创建: {response.json()['request_id']}")
            else:
                st.error(response.text)


# Main content
if page == "📊 健康监控":
    toolbar_left, toolbar_right = st.columns([5, 1])
    with toolbar_right:
        if st.button("刷新数据", use_container_width=True, key="overview-refresh"):
            st.rerun()
    with st.spinner("正在采集数据..."):
        collector = ClusterCollector(st.session_state.db_connector)
        result = collector.collect()

    if result['status'] in {'success', 'partial'}:
        data = result['data']
        nodes = data.get('nodes', [])
        connectivity = data.get('node_connectivity', [])
        connectivity_by_name = {item.get('node_name'): item for item in connectivity}
        online_nodes = sum(item.get('status') == 'reachable' for item in connectivity)
        unavailable_nodes = [
            item for item in connectivity if item.get('status') == 'unreachable'
        ]
        conn_info = data.get('connections', {})
        conn_total = conn_info.get('total')
        conn_max = conn_info.get('max_connections')
        usage = conn_info.get('usage_percent')
        replication = data.get('replication', [])
        automation = {}
        latest_audit = None
        latest_detail = {}
        api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
        try:
            automation_response = requests.get(f"{api_base}/api/automation/status", timeout=8)
            automation_response.raise_for_status()
            automation = automation_response.json()
            audit_response = requests.get(
                f"{api_base}/api/audits",
                params={"limit": 1, "audit_type": "readonly_health_audit"},
                timeout=8,
            )
            audit_response.raise_for_status()
            audits = audit_response.json().get("items", [])
            if audits:
                latest_audit = audits[0]
                detail_response = requests.get(
                    f"{api_base}/api/audits/{latest_audit['audit_id']}", timeout=8
                )
                detail_response.raise_for_status()
                latest_detail = detail_response.json()
        except requests.RequestException as error:
            logger.warning("Could not load latest audit for overview: %s", error)

        latest_evidence = latest_detail.get("evidence") or {}
        latest_findings = latest_evidence.get("findings") or []
        collection_status = latest_evidence.get("collection_status")
        if unavailable_nodes or result['status'] == 'partial' or collection_status == 'partial':
            status_class = "partial"
            status_label = "需要关注"
            status_detail = "部分节点不可达或最近一次巡检数据不完整"
        elif result['status'] == 'error':
            status_class = "error"
            status_label = "采集异常"
            status_detail = "无法完整读取集群状态"
        else:
            status_class = ""
            status_label = "集群连接正常"
            status_detail = f"{online_nodes}/{len(nodes)} 个注册节点网络可达"
        last_audit_time = latest_audit.get("created_at") if latest_audit else None
        st.markdown(
            f'<div class="overview-status {status_class}"><div>'
            f'<div class="status-title">{status_label}</div>'
            f'<div class="status-detail">{status_detail}</div></div>'
            f'<div class="status-time">最近巡检 · {html.escape(str(last_audit_time or "暂无记录"))}</div></div>',
            unsafe_allow_html=True,
        )

        node_count = len(nodes)
        replication_count = len(replication)
        finding_count = len(latest_findings)
        metric_columns = st.columns(4)
        metric_values = [
            ("注册节点", f"{online_nodes}/{node_count}", "CN、DN 与 GTM 网络探测"),
            ("CN 连接占用", f"{conn_total or 0}/{conn_max or '—'}", f"{usage:.1f}% 使用率" if usage is not None else "容量数据不可用"),
            ("复制连接", str(replication_count), "当前 CN 可见的复制会话"),
            ("最近巡检发现", str(finding_count), f"风险等级 · {latest_audit.get('risk_level', '未知') if latest_audit else '暂无记录'}"),
        ]
        for column, (label, value, detail) in zip(metric_columns, metric_values):
            with column:
                st.metric(label, value, help=detail)

        if usage is not None:
            progress_value = min(max(float(usage) / 100, 0), 1)
            st.progress(progress_value, text=f"CN 客户端连接容量 · {usage:.1f}%")

        st.markdown(
            '<div class="section-heading"><h3>集群拓扑</h3>'
            f'<span class="section-note">{len(nodes)} 个注册节点 · CN 连接入口 {html.escape(str(st.session_state.config.DB_HOST))}:{st.session_state.config.DB_PORT}</span></div>',
            unsafe_allow_html=True,
        )
        if nodes:
            node_columns = st.columns(min(len(nodes), 4))
            role_names = {"C": "协调节点 · CN", "D": "数据节点 · DN", "G": "事务管理器 · GTM"}
            for index, node in enumerate(nodes):
                probe = connectivity_by_name.get(node.get("node_name"), {})
                node_status = probe.get("status", "unknown")
                status_label = {"reachable": "可达", "unreachable": "不可达", "unknown": "未知"}.get(node_status, "未知")
                status_class_name = {"reachable": "online", "unreachable": "offline", "unknown": "unknown"}.get(node_status, "unknown")
                node_name = html.escape(str(node.get("node_name", "未命名")))
                host = html.escape(str(node.get("node_host", "未知")))
                port = html.escape(str(node.get("node_port", "—")))
                role = role_names.get(node.get("node_type"), "数据库节点")
                with node_columns[index % len(node_columns)]:
                    st.markdown(
                        f'<div class="node-card"><div class="node-card-top">'
                        f'<span class="node-name">{node_name}</span>'
                        f'<span class="node-state {status_class_name}">{status_label}</span></div>'
                        f'<div class="node-role">{role}</div>'
                        f'<div class="node-endpoint">{host}:{port}</div></div>',
                        unsafe_allow_html=True,
                    )
        else:
            st.info("未发现注册节点")

        left_column, right_column = st.columns([1.25, 1])
        with left_column:
            st.markdown(
                '<div class="section-heading"><h3>最近巡检信号</h3>'
                '<span class="section-note">来自最近一次持久化审计</span></div>',
                unsafe_allow_html=True,
            )
            if latest_audit:
                diagnosis = (latest_detail.get("ai_analysis") or {}).get("structured") or {}
                if diagnosis.get("root_cause"):
                    st.markdown(f"**AI 判断**  \n{diagnosis['root_cause']}")
                if latest_findings:
                    for finding in latest_findings[:5]:
                        severity = html.escape(str(finding.get("severity", "unknown")).lower())
                        check = html.escape(str(finding.get("check", "巡检发现")))
                        observed = html.escape(str(finding.get("observed", "")))
                        st.markdown(
                            f'<div class="finding-row"><div class="finding-top">'
                            f'<span class="finding-name">{check}</span>'
                            f'<span class="finding-severity {severity}">{severity}</span></div>'
                            f'<div class="finding-description">{observed}</div></div>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.success("最近一次巡检没有规则告警")
            else:
                st.info("还没有健康巡检记录。运行一次 AI 巡检后，发现和诊断会显示在这里。")
        with right_column:
            st.markdown(
                '<div class="section-heading"><h3>值班操作</h3>'
                '<span class="section-note">按需启动诊断或复核</span></div>',
                unsafe_allow_html=True,
            )
            action_left, action_right = st.columns(2)
            with action_left:
                st.button(
                    "运行 AI 巡检", type="primary", use_container_width=True,
                    key="overview-run-audit", on_click=navigate_to_page,
                    args=("🛡️ AI 巡检",),
                )
            with action_right:
                st.button(
                    "打开 Agent", use_container_width=True, key="overview-open-agent",
                    on_click=navigate_to_page, args=("💬 Agent 助手",),
                )
            if latest_audit:
                st.caption(
                    f"审计 ID · {latest_audit['audit_id']}  ·  "
                    f"采集状态 · {collection_status or '未知'}  ·  "
                    f"巡检周期 · {automation.get('interval_seconds', '—')} 秒"
                )
            if unavailable_nodes:
                st.error("不可达节点: " + ", ".join(item.get("node_name", "未知") for item in unavailable_nodes))

        bottom_left, bottom_right = st.columns([1, 1])
        with bottom_left:
            st.markdown('<div class="section-heading"><h3>复制链路</h3></div>', unsafe_allow_html=True)
            if replication:
                st.dataframe(replication, use_container_width=True, hide_index=True)
            else:
                st.caption("当前 CN 未报告复制会话。")
        with bottom_right:
            st.markdown('<div class="section-heading"><h3>连接分布</h3></div>', unsafe_allow_html=True)
            connections = conn_info.get('by_database', [])
            if connections:
                st.dataframe(connections, use_container_width=True, hide_index=True)
            else:
                st.caption("当前没有可展示的客户端连接记录。")

    else:
        st.error(f"数据采集失败: {result.get('error', 'unknown')}")

elif page == "🛡️ 只读巡检":
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        automation = requests.get(f"{api_base}/api/automation/status", timeout=10).json()
        repair_readiness = automation.get("repair_readiness") or {}
        status_columns = st.columns(3)
        with status_columns[0]:
            st.metric("周期巡检", "运行中" if automation.get("automatic_health_audit_enabled") else "已关闭",
                      help=f"间隔 {automation.get('interval_seconds', '—')} 秒")
        with status_columns[1]:
            st.metric("自动修复", "已启用" if automation.get("automatic_repair_enabled") else "未启用")
        with status_columns[2]:
            st.metric("修复执行器", "就绪" if repair_readiness.get("ready") else "未就绪")
        if not repair_readiness.get("executor_ready"):
            st.warning(
                "修复执行账号或数据库函数未就绪。系统会生成审计和建议，但不会执行数据库修复。"
            )
            if repair_readiness.get("reason"):
                st.caption(f"未就绪原因：{repair_readiness['reason']}")
        elif automation.get("automatic_repair_enabled") and not repair_readiness.get("ready"):
            st.warning("自动修复目标尚未通过数据库管理员白名单检查。")
            if repair_readiness.get("reason"):
                st.caption(f"未就绪原因：{repair_readiness['reason']}")
        if automation.get("automatic_repair_enabled"):
            if automation.get("automatic_repair_ready"):
                st.caption(
                    "定时自动修复已就绪 · 目标 "
                    + (", ".join(automation.get("automatic_repair_targets") or []) or "未配置")
                )
    except Exception as error:
        st.warning(f"读取周期巡检状态失败: {error}")

    with st.container(border=True):
        st.markdown("#### 启动一次巡检")
        target_column, run_column = st.columns([3, 1])
        with target_column:
            statistics_target = st.text_input(
                "统计目标表（留空执行全库巡检）",
                placeholder="public.orders",
                key="health-audit-target",
            ).strip()
        with run_column:
            st.write("")
            run_audit = st.button("运行 AI 巡检", type="primary", use_container_width=True)
    if run_audit:
        st.session_state.pop("last_health_audit", None)
        with st.status("正在启动巡检") as status:
            try:
                params = {"table": statistics_target} if statistics_target else None
                stages = {
                    "starting": "正在启动巡检",
                    "collecting": "正在采集 OpenTenBase 状态",
                    "diagnosing": "正在生成诊断报告",
                    "saving": "正在保存审计记录",
                }
                with requests.post(
                    f"{api_base}/api/audits/health/stream", params=params, stream=True,
                    timeout=st.session_state.config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines(chunk_size=1):
                        if not line.startswith(b"data:"):
                            continue
                        event = json.loads(line[5:])
                        if event["type"] == "progress":
                            status.update(label=stages[event["stage"]])
                            continue
                        if event["type"] == "result":
                            st.session_state.last_health_audit = event["audit"]
                            status.update(label="巡检已完成", state="complete")
                        elif event["type"] == "busy":
                            status.update(label="已有巡检正在运行", state="complete")
                        else:
                            status.update(label="服务端巡检失败", state="error")
                        break
                    else:
                        status.update(label="巡检连接已中断，请到巡检历史确认结果", state="error")
            except requests.exceptions.Timeout:
                status.update(label="等待巡检响应超时，请到巡检历史确认结果", state="error")
            except Exception as error:
                status.update(label="巡检连接失败", state="error")
                st.error(f"巡检失败: {error}")
    audit = st.session_state.get("last_health_audit")
    if audit:
        retried_analysis = render_reanalysis_button(
            api_base, audit["audit_id"], audit, "health-reanalyze"
        )
        if retried_analysis:
            audit.update(retried_analysis)
            st.session_state.last_health_audit = audit
        evidence = audit.get("evidence") or {}
        render_collection_status(evidence)
        render_automatic_repair(evidence)
        render_analysis_status(audit)
        findings = audit.get("findings", [])
        structured = audit.get("structured") or {}
        summary_tab, findings_tab, evidence_tab = st.tabs(["诊断结论", f"发现 · {len(findings)}", "证据与引用"])
        with summary_tab:
            summary_columns = st.columns([1, 3])
            with summary_columns[0]:
                st.metric("风险等级", str(audit.get("risk_level", "unknown")).upper())
                st.caption(f"审计 ID · {audit['audit_id']}")
            with summary_columns[1]:
                st.markdown("#### 根因分析")
                st.write(structured.get("root_cause") or "模型没有返回根因判断，请结合证据复核。")
                recommendations = structured.get("recommendations") or []
                if recommendations:
                    st.markdown("#### 下一步建议")
                    for recommendation in recommendations:
                        st.markdown(f"- {recommendation}")
        with findings_tab:
            if findings:
                for index, finding in enumerate(findings):
                    severity = str(finding.get("severity", "unknown")).upper()
                    title = f"{severity} · {finding.get('check', '巡检发现')} · {finding.get('observed', '')}"
                    with st.expander(title, expanded=index == 0):
                        st.json(finding.get("evidence", {}))
                render_repair_proposal(api_base, audit["audit_id"], findings)
            elif evidence.get("collection_status") == "success":
                st.success("未发现规则告警")
            else:
                st.info("当前审计未产生规则发现，请结合采集状态查看是否存在数据缺口。")
        with evidence_tab:
            st.markdown("#### 本次采集证据")
            st.json(audit.get("evidence", {}))
            refs = audit.get("knowledge_refs", [])
            st.markdown(f"#### 知识引用 · {len(refs)}")
            if refs:
                st.dataframe(refs, use_container_width=True, hide_index=True)
            else:
                st.caption("本次分析没有返回知识库引用。")

elif page == "📜 巡检历史":
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        risks = {"全部": None, "高与严重": "high_or_critical", "仅严重": "critical"}
        filter_columns = st.columns([1, 1, 1])
        with filter_columns[0]:
            risk = risks[st.selectbox("风险等级", list(risks))]
        with filter_columns[1]:
            table_filter = st.text_input("目标表", placeholder="public.orders").strip()
        with filter_columns[2]:
            database_filter = st.text_input("数据库", placeholder="postgres").strip()
        response = requests.get(
            f"{api_base}/api/audits",
            params={
                "limit": 50, "risk": risk, "table": table_filter or None,
                "database": database_filter or None,
            },
            timeout=10,
        )
        response.raise_for_status()
        history = response.json()
        items = history.get("items", [])
        if items:
            high_count = sum(item.get("risk_level") in {"high", "critical"} for item in items)
            partial_count = sum(item.get("collection_status") == "partial" for item in items)
            summary_columns = st.columns(3)
            summary_columns[0].metric("记录数", len(items))
            summary_columns[1].metric("高风险", high_count)
            summary_columns[2].metric("部分采集", partial_count)
            type_labels = {
                "readonly_health_audit": "健康巡检",
                "readonly_lock_audit": "锁诊断",
            }
            rows = [{
                "时间": item.get("created_at"),
                "数据库": item.get("database") or "—",
                "类型": type_labels.get(item.get("audit_type"), item.get("audit_type")),
                "风险": str(item.get("risk_level") or "unknown").upper(),
                "采集": {"success": "完整", "partial": "部分", "error": "失败"}.get(item.get("collection_status"), "—"),
                "发现": item.get("finding_count", 0),
                "引用": item.get("reference_count", 0),
                "触发": {"scheduled": "周期", "manual": "手动", "alertmanager": "告警"}.get(item.get("trigger"), "—"),
            } for item in items]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            audit_options = {
                f"{item.get('created_at')} · {type_labels.get(item.get('audit_type'), item.get('audit_type'))} · "
                f"{str(item.get('risk_level') or 'unknown').upper()} · {item.get('audit_id')}": item["audit_id"]
                for item in items
            }
            selected_id = audit_options[st.selectbox("审计详情", list(audit_options))]
            if selected_id:
                response = requests.get(f"{api_base}/api/audits/{selected_id}", timeout=10)
                response.raise_for_status()
                detail = response.json()
                evidence = detail.get("evidence") or {}
                render_collection_status(evidence)
                render_automatic_repair(evidence)
                render_repair_proposal(api_base, selected_id, evidence.get("findings", []))
                analysis = detail.get("ai_analysis") or {}
                retried_analysis = render_reanalysis_button(
                    api_base, selected_id, analysis, "history-reanalyze"
                )
                if retried_analysis:
                    analysis = retried_analysis
                render_analysis_status(analysis)
                analysis_structured = analysis.get("structured") or {}
                diagnosis_tab, evidence_tab, knowledge_tab = st.tabs(["分析", "采集证据", "知识引用"])
                with diagnosis_tab:
                    st.markdown("#### 根因分析")
                    st.write(analysis_structured.get("root_cause") or "暂无根因判断")
                    for recommendation in analysis_structured.get("recommendations") or []:
                        st.markdown(f"- {recommendation}")
                with evidence_tab:
                    st.json(detail.get("evidence", {}))
                with knowledge_tab:
                    refs = detail.get("knowledge_refs") or []
                    if refs:
                        st.dataframe(refs, use_container_width=True, hide_index=True)
                    else:
                        st.caption("没有知识库引用")
        else:
            st.info("暂无符合筛选条件的巡检记录")
    except Exception as error:
        st.error(f"读取巡检历史失败: {error}")

elif page == "🧾 修复审批":
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        queues = {"待审批": "pending", "待复核": "review", "全部记录": None}
        queue_column, page_column = st.columns([3, 1])
        with queue_column:
            queue = queues[st.selectbox("请求队列", list(queues))]
        with page_column:
            page_number = st.number_input("页码", min_value=1, step=1, key=f"repair-page-{queue}")
        response = requests.get(
            f"{api_base}/api/repairs",
            params={"limit": 50, "offset": (page_number - 1) * 50, "queue": queue},
            timeout=10,
        )
        response.raise_for_status()
        decision = st.session_state.pop("repair_decision", None)
        if decision:
            st.json(decision)
        items = response.json().get("items", [])
        if not items:
            st.info("暂无修复请求")
        else:
            counts = st.columns(4)
            status_counts = {
                "pending": sum(item.get("status") == "pending" for item in items),
                "executing": sum(item.get("status") == "executing" for item in items),
                "unverified": sum(item.get("status") == "unverified" for item in items),
                "failed": sum(item.get("status") == "failed" for item in items),
            }
            for column, (name, label) in zip(counts, [
                ("pending", "待审批"), ("executing", "执行中"),
                ("unverified", "待复核"), ("failed", "执行失败"),
            ]):
                column.metric(label, status_counts[name])
        status_labels = {
            "pending": "待审批", "executing": "执行中", "unverified": "待复核",
            "executed": "已验证", "failed": "执行失败", "rejected": "已拒绝",
            "closed": "已关闭", "expired": "已过期",
        }
        operation_labels = {"analyze_table": "刷新表统计 ANALYZE", "cancel_query": "取消查询建议"}
        for item in items:
            status_label = status_labels.get(item.get("status"), item.get("status"))
            operation_label = operation_labels.get(item.get("operation"), item.get("operation"))
            with st.expander(f"{status_label} · {operation_label} · {item['request_id']}"):
                proposal_evidence = item.get("evidence") or {}
                risk_policy = proposal_evidence.get("risk_policy") or {}
                human_approval = proposal_evidence.get("human_approval") or {}
                requires_human = risk_policy.get("requires_human_approval", True)
                suggestion_only = item.get("operation") == "cancel_query"
                if risk_policy:
                    risk_name = {"low": "低风险", "moderate": "中风险", "high": "高风险", "unknown": "未知风险"}.get(
                        risk_policy.get("risk_level"), "未知风险"
                    )
                    st.caption(f"风险等级：{risk_name} · {risk_policy.get('reason', '')}")
                ready = not requires_human or human_approval.get("approved") is True
                if requires_human and not ready:
                    st.warning("此操作需要人工批准后执行")
                elif ready and not suggestion_only:
                    st.success("风险策略满足，可执行")
                if suggestion_only:
                    st.warning("当前为建议模式。逐 DN 取消执行器尚未启用，批准不会执行数据库操作。")
                if proposal_evidence.get("proposal_source") == "stale_table_statistics":
                    st.caption("提案来源 · 表统计过时巡检规则")
                stale_nodes = (proposal_evidence.get("observation") or {}).get("stale_nodes") or []
                if stale_nodes:
                    st.caption(f"统计过时节点 · {', '.join(stale_nodes)}")
                render_analysis_status(proposal_evidence.get("ai_analysis"))
                st.json({"parameters": item.get("parameters"), "evidence": proposal_evidence, "reason": item.get("reason")})
                audit_id = item.get("audit_id")
                if audit_id and st.checkbox("查看原始巡检", key=f"source-audit-{item['request_id']}"):
                    st.caption(f"审计 ID {audit_id}")
                    source = requests.get(f"{api_base}/api/audits/{audit_id}", timeout=10)
                    if source.status_code == 404:
                        st.info("原始巡检记录已无法读取。")
                    elif source.ok:
                        audit = source.json()
                        evidence = audit.get("evidence") or {}
                        render_collection_status(evidence)
                        render_analysis_status(audit.get("ai_analysis"))
                        st.json({
                            "风险等级": audit.get("risk_level"),
                            "发现": evidence.get("findings") or [],
                            "AI 分析": audit.get("ai_analysis"),
                            "知识引用": audit.get("knowledge_refs") or [],
                        })
                    else:
                        st.error(f"读取原始巡检失败（HTTP {source.status_code}）")
                if item.get("approved_at"):
                    st.write("审核记录", item["approved_at"], item.get("approved_by"))
                if item["status"] == "executing":
                    st.warning("执行结果尚未入库。进程中断时此状态可能保留，请核对目标库统计和服务日志。")
                elif item["status"] == "unverified":
                    st.warning("执行结果未通过复查，请核对各 DN 的统计时间戳。")
                elif item["status"] == "closed":
                    st.info("人工复核后已关闭，不会自动重试。")
                elif item["status"] == "failed":
                    st.error("修复执行失败")
                if item.get("result") is not None:
                    st.write("已保存的处置结果")
                    for notice in (item["result"].get("database_notices") or []):
                        st.warning(notice)
                    st.json(item["result"])
                if item.get("manual_review"):
                    st.write("人工复核记录")
                    st.json(item["manual_review"])
                elif item["status"] in {"executing", "unverified"}:
                    with st.form(f"review-{item['request_id']}"):
                        disposition = st.selectbox(
                            "复核处置",
                            options=["confirmed", "closed_no_retry"],
                            format_func=lambda value: "确认已核查" if value == "confirmed" else "关闭且不重试",
                        )
                        note = st.text_area("复核结论与依据", max_chars=4000)
                        review_token = st.text_input("审批令牌", type="password")
                        if st.form_submit_button("提交人工复核"):
                            response = requests.post(
                                f"{api_base}/api/repairs/{item['request_id']}/manual-review",
                                json={"disposition": disposition, "note": note, "token": review_token}, timeout=10,
                            )
                            if response.ok:
                                st.rerun()
                            st.error(response.text)
                if item["status"] == "pending" and not suggestion_only:
                    approver = st.session_state.config.AIOPS_APPROVER_ID
                    token = st.text_input("审批令牌", type="password", key=f"t-{item['request_id']}")
                    left, right = st.columns(2)
                    if left.button("人工批准", key=f"human-approve-{item['request_id']}",
                                   disabled=not requires_human or human_approval.get("approved") is True):
                        response = requests.post(
                            f"{api_base}/api/repairs/{item['request_id']}/human-approval",
                            json={"token": token}, timeout=10,
                        )
                        if response.ok:
                            st.rerun()
                        st.error(response.text)
                    if human_approval.get("approved"):
                        st.caption(f"人工批准人：{human_approval.get('approver')}")
                    if right.button("执行已批准操作", key=f"approve-{item['request_id']}", disabled=not ready):
                        try:
                            response = requests.post(
                                f"{api_base}/api/repairs/{item['request_id']}/approve",
                                json={"approver": approver, "token": token},
                                timeout=30,
                            )
                        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                            st.warning(
                                f"未收到审批结果（请求 {item['request_id']}）。"
                                "服务端可能仍在执行，请先刷新审批队列并核对状态。"
                            )
                        else:
                            if response.ok:
                                st.session_state.repair_decision = response.json()
                                st.rerun()
                            st.error(response.text)
                    reject_reason = st.text_input("拒绝原因", key=f"r-{item['request_id']}")
                    if st.button("拒绝", key=f"reject-{item['request_id']}"):
                        response = requests.post(f"{api_base}/api/repairs/{item['request_id']}/reject", json={"approver": approver, "reason": reject_reason, "token": token}, timeout=10)
                        if response.ok:
                            st.session_state.repair_decision = response.json()
                            st.rerun()
                        st.error(response.text)
    except Exception as error:
        st.error(f"读取修复审批失败: {error}")

elif page == "💬 智能问答":
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        st.markdown("#### 开始一次运维调查")
        st.caption("描述异常或目标，Agent 会按需检查集群、查询知识库并执行你明确提出的 SQL。")
        prompt_suggestions = [
            "检查当前集群状态并指出最需要关注的问题",
            "分析最近一次巡检的主要发现和证据",
            "查看当前数据节点锁等待与阻塞会话",
        ]
        suggestion_columns = st.columns(len(prompt_suggestions))
        for column, suggestion in zip(suggestion_columns, prompt_suggestions):
            with column:
                st.button(
                    suggestion, use_container_width=True, key=f"agent-suggestion-{suggestion[:8]}",
                    on_click=set_chat_prompt, args=(suggestion,),
                )

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("tool_trace"):
                with st.expander("工具调用与执行记录"):
                    st.json(message["tool_trace"])

    if prompt := st.chat_input("描述数据库问题，或输入要检查的 SQL…", key="agent_chat_input"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if st.session_state.llm_client:
                with st.spinner("思考中..."):
                    try:
                        api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
                        history = [
                            {"role": message["role"], "content": message["content"]}
                            for message in st.session_state.messages[:-1]
                            if message["role"] in {"user", "assistant"}
                        ][-16:]
                        response = requests.post(
                            f"{api_base}/api/qa/ask",
                            json={"question": prompt, "include_context": True, "history": history},
                            timeout=900,
                        )
                        response.raise_for_status()
                        result = response.json()
                        answer = result.get("answer", "")
                        st.markdown(answer)
                        trace = result.get("tool_trace") or []
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": answer,
                            "tool_trace": trace,
                        })
                    except Exception as e:
                        error_msg = f"抱歉，处理您的问题时出错了: {str(e)}"
                        st.error(error_msg)
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": error_msg
                        })
            else:
                error_msg = "LLM 客户端未初始化，请检查 API 配置"
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg
                })

    if st.session_state.messages:
        if st.button("清空当前会话", key="clear-agent-chat"):
            st.session_state.messages = []
            st.rerun()

elif page == "🧪 SQL 审核":
    st.markdown("SQL 审核只评估语句风险；勾选 EXPLAIN 时，仅生成只读执行计划。")
    examples = {
        "选择一个查询模板…": "",
        "查看当前连接": "SELECT datname, state, count(*) AS sessions FROM pg_catalog.pg_stat_activity GROUP BY datname, state ORDER BY sessions DESC;",
        "查看活动会话": "SELECT pid, usename, datname, application_name, state, wait_event_type, wait_event FROM pg_catalog.pg_stat_activity WHERE backend_type = 'client backend' ORDER BY state, pid;",
        "查看表统计": "SELECT schemaname, relname, n_live_tup, n_dead_tup FROM pg_catalog.pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20;",
    }
    template_column, explain_column = st.columns([3, 1])
    with template_column:
        selected_example = st.selectbox("查询模板", list(examples), label_visibility="collapsed")
    with explain_column:
        explain = st.toggle("只读 EXPLAIN", value=True)
    if selected_example != "查询模板…":
        st.button(
            "载入模板", key="load-sql-template", on_click=load_sql_template,
            args=(examples[selected_example],),
        )
    sql_text = st.text_area(
        "SQL 语句", height=230, placeholder="SELECT ...", key="sql_review_editor"
    )
    audit_column, clear_column = st.columns([1, 5])
    with audit_column:
        run_sql_review = st.button("审核 SQL", type="primary", disabled=not sql_text.strip())
    if run_sql_review:
        api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
        try:
            response = requests.post(f"{api_base}/api/sql-audit", json={"sql": sql_text, "explain": explain}, timeout=15)
            response.raise_for_status()
            report = response.json()
            level = report.get("risk_level", "unknown")
            risk_label = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}.get(level, "未知")
            st.metric("语句风险", risk_label)
            if report.get("findings"):
                st.markdown("#### 风险发现")
                st.dataframe(report["findings"], use_container_width=True, hide_index=True)
            if report.get("explain_error"):
                st.warning(report["explain_error"].get("message", "EXPLAIN 失败"))
            elif report.get("explain") is not None:
                st.markdown("#### 执行计划")
                st.json(report["explain"])
        except Exception as error:
            st.error(f"SQL 审核失败：{error}")

elif page == "🔍 性能诊断":
    st.markdown('<div class="main-header">🔍 性能诊断</div>', unsafe_allow_html=True)
    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["锁分析", "长查询", "表统计"])

    with tab1:
        st.markdown("### 🔒 锁信息")

        if st.button("刷新锁信息", key="refresh_locks"):
            with st.spinner("正在查询..."):
                collector = PerformanceCollector(
                    st.session_state.db_connector,
                    st.session_state.config
                )
                result = collector.collect()

                if result['status'] == 'success':
                    lock_info = result['data'].get('locks', {})

                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("总锁数", lock_info.get('total_locks', 0))
                    with col2:
                        blocked = lock_info.get('blocked_count', 0)
                        st.metric("阻塞锁", blocked,
                                 delta_color="inverse" if blocked > 0 else "normal")

                    blocking_locks = lock_info.get('blocking_locks', [])
                    if blocking_locks:
                        st.warning(f"⚠️ 发现 {len(blocking_locks)} 个阻塞锁")
                        st.dataframe(blocking_locks, use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ 没有检测到阻塞锁")

                    st.markdown("#### 所有活跃锁")
                    all_locks = lock_info.get('all_locks', [])
                    if all_locks:
                        st.dataframe(all_locks, use_container_width=True, hide_index=True)
                else:
                    st.error(f"查询失败: {result.get('error', 'unknown')}")

    with tab2:
        st.markdown("### ⏱️ 长时间运行的查询")

        if st.button("查询", key="refresh_long_queries"):
            with st.spinner("正在查询..."):
                collector = PerformanceCollector(
                    st.session_state.db_connector,
                    st.session_state.config
                )
                result = collector.collect()

                if result['status'] == 'success':
                    queries = result['data'].get('long_running_queries', [])

                    if queries:
                        st.warning(f"⚠️ 发现 {len(queries)} 个长查询")
                        st.dataframe(queries, use_container_width=True, hide_index=True)
                    else:
                        st.success("✅ 没有检测到长时间运行的查询")
                else:
                    st.error(f"查询失败: {result.get('error', 'unknown')}")

    with tab3:
        st.markdown("### 📊 表统计信息")

        if st.button("查询表统计", key="refresh_table_stats"):
            with st.spinner("正在查询..."):
                collector = PerformanceCollector(
                    st.session_state.db_connector,
                    st.session_state.config
                )
                result = collector.collect()

                if result['status'] == 'success':
                    table_stats = result['data'].get('table_stats', [])

                    if table_stats:
                        st.dataframe(table_stats, use_container_width=True, hide_index=True)
                    else:
                        st.info("暂无表统计信息")
                else:
                    st.error(f"查询失败: {result.get('error', 'unknown')}")
