"""Product-oriented OpenTenBase AIOps console.

The console keeps the course demo workflows visible: live topology, AI health
audits, evidence, SQL review, repair review, and the interactive Agent.
"""
import json
import os
import sys
from pathlib import Path

import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.collectors.cluster import ClusterCollector
from backend.collectors.performance import PerformanceCollector
from backend.engines.repair_workflow import has_repair_identity
from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector


st.set_page_config(page_title="OpenTenBase AIOps", page_icon="OTB", layout="wide")

API = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
config = st.session_state.setdefault("config", Config())
st.session_state.setdefault("db", OpenTenBaseConnector(config))

st.markdown("""
<style>
:root { --bg:#f4f7f8; --surface:#fff; --ink:#17252c; --muted:#687b84; --line:#d9e3e6;
        --teal:#087d77; --amber:#bc7418; --red:#bd4d48; --green:#31825d; }
html, body, [data-testid="stAppViewContainer"] { background:var(--bg); color:var(--ink); }
[data-testid="stHeader"] { background:transparent; }
.main .block-container { max-width:1600px; padding:1.35rem 2.2rem 3rem; }
[data-testid="stSidebar"] { background:#17272e; border-right:1px solid #2d4148; }
[data-testid="stSidebar"] * { color:#eaf1f2; }
[data-testid="stSidebar"] hr { border-color:#395057; }
[data-testid="stSidebar"] [role="radiogroup"] { gap:.2rem; }
[data-testid="stSidebar"] [role="radiogroup"] label { padding:.56rem .65rem; border-radius:6px; }
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:#263d45; }
.brand { display:flex; gap:.7rem; align-items:center; padding:.25rem .2rem 1rem; }
.brand-mark { width:2.35rem; height:2.35rem; border-radius:6px; display:grid; place-items:center;
              background:#087d77; color:white; font-weight:800; font-size:.78rem; }
.brand-name { font-weight:750; color:#fff; font-size:1.05rem; line-height:1.1; }
.brand-sub { color:#9fb2b7; font-size:.73rem; margin-top:.2rem; }
.nav-label { color:#91a6ac; font-size:.68rem; letter-spacing:.1em; font-weight:700; margin:.7rem .2rem .2rem; }
.topline { display:flex; justify-content:space-between; align-items:flex-start; border-bottom:1px solid var(--line);
           padding:.2rem 0 1rem; margin-bottom:1.2rem; }
.eyebrow { color:var(--teal); font-size:.68rem; font-weight:800; letter-spacing:.1em; }
.title { color:var(--ink); font-size:1.6rem; font-weight:760; margin-top:.25rem; }
.subtitle { color:var(--muted); font-size:.86rem; margin-top:.35rem; }
.context { color:var(--muted); text-align:right; font-size:.76rem; line-height:1.55; }
.dot { display:inline-block; width:.48rem; height:.48rem; border-radius:50%; background:#40956c; margin-right:.35rem; }
.signal { border:1px solid #b9d8c9; border-left:4px solid var(--green); background:#edf7f0; border-radius:6px;
          padding:.75rem .95rem; margin-bottom:1rem; }
.signal.partial { border-color:#e9d09d; border-left-color:var(--amber); background:#fff8ea; }
.signal.error { border-color:#e7c0bd; border-left-color:var(--red); background:#fff1ef; }
.signal-title { font-weight:750; font-size:.86rem; }
.signal-detail { color:var(--muted); font-size:.76rem; margin-top:.18rem; }
.section { display:flex; justify-content:space-between; align-items:baseline; margin:1.25rem 0 .62rem; }
.section h3 { font-size:1rem; margin:0; font-weight:750; }
.section span { color:var(--muted); font-size:.75rem; }
.node { border:1px solid var(--line); background:var(--surface); border-radius:6px; padding:.78rem; min-height:100px; }
.node-top { display:flex; justify-content:space-between; gap:.4rem; }
.node-name { font-weight:750; font-size:.87rem; }
.node-role { color:var(--muted); font-size:.71rem; margin-top:.28rem; }
.node-endpoint { font-family:ui-monospace,Consolas,monospace; color:#4d626d; font-size:.72rem; margin-top:.48rem; }
.state { border-radius:999px; padding:.12rem .4rem; font-size:.65rem; font-weight:750; }
.state.ok { color:#2d7853; background:#e7f4ec; } .state.bad { color:#a23d38; background:#fae8e6; }
.state.unknown { color:#667984; background:#edf1f3; }
.finding { border-bottom:1px solid var(--line); padding:.68rem 0; }
.finding:last-child { border-bottom:0; }
.finding-top { display:flex; justify-content:space-between; gap:.6rem; }
.finding-name { font-size:.82rem; font-weight:700; }
.finding-sev { font-size:.66rem; font-weight:800; text-transform:uppercase; }
.high,.critical { color:var(--red); } .medium { color:var(--amber); } .low { color:#3579ae; }
.finding-detail { color:var(--muted); font-size:.75rem; line-height:1.45; margin-top:.22rem; }
[data-testid="stMetric"] { background:var(--surface); border:1px solid var(--line); border-radius:6px; padding:.75rem .9rem; }
[data-testid="stMetricLabel"] { color:var(--muted); font-size:.75rem; }
[data-testid="stMetricValue"] { color:var(--ink); font-size:1.48rem; font-weight:760; }
div.stButton > button { border-radius:6px; font-weight:700; min-height:2.4rem; }
div.stButton > button[kind="primary"] { background:var(--teal); border-color:var(--teal); color:white; }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:6px; overflow:hidden; }
[data-testid="stExpander"] { border-color:var(--line); border-radius:6px; }
@media(max-width:900px){ .main .block-container{padding:1rem;} .topline{display:block;} .context{text-align:left;margin-top:.6rem;} }
</style>
""", unsafe_allow_html=True)


PAGES = {
    "总览": "overview", "AI 巡检": "audit", "巡检记录": "history",
    "处置中心": "repairs", "Agent 助手": "agent", "性能工具": "performance", "SQL 审核": "sql",
}


def go(page):
    st.session_state["page"] = page


st.session_state.setdefault("page", "overview")
st.session_state.setdefault("agent_sessions", {})
st.session_state.setdefault("active_agent_session", None)
with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">OTB</div><div><div class="brand-name">OpenTenBase</div><div class="brand-sub">AIOps 运维控制台</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="nav-label">监控与诊断</div>', unsafe_allow_html=True)
    selected = st.radio("导航", list(PAGES), index=list(PAGES.values()).index(st.session_state.page), label_visibility="collapsed")
    if PAGES[selected] != st.session_state.page:
        st.session_state.page = PAGES[selected]
        st.rerun()
    st.markdown('<div class="nav-label">连接</div>', unsafe_allow_html=True)
    if st.button("测试数据库连接", use_container_width=True):
        status = st.session_state.db.test_connection()
        st.success("连接正常" if status.get("connected") else "连接失败")
    st.caption(f"{config.DB_HOST}:{config.DB_PORT}")
    st.caption(f"{config.DB_NAME} · {config.DB_USER}")


META = {
    "overview": ("总览", "集群健康、风险信号与最新 AI 结论"),
    "audit": ("AI 巡检", "采集真实 OpenTenBase 证据并生成可追溯诊断"),
    "history": ("巡检记录", "查看历史审计、发现和知识引用"),
    "repairs": ("处置中心", "处理 AI 建议、审批和执行后复核"),
    "agent": ("Agent 助手", "通过自然语言调查集群并调用数据库工具"),
    "performance": ("性能工具", "锁、长查询和数据节点统计"),
    "sql": ("SQL 审核", "风险识别与只读执行计划"),
}
page_title, page_subtitle = META[st.session_state.page]
st.markdown(f'<div class="topline"><div><div class="eyebrow">OPENTENBASE / AIOPS</div><div class="title">{page_title}</div><div class="subtitle">{page_subtitle}</div></div><div class="context"><span class="dot"></span>{config.DB_HOST}:{config.DB_PORT}<br>{config.DB_NAME}</div></div>', unsafe_allow_html=True)


def api_json(path, **kwargs):
    response = requests.get(f"{API}{path}", timeout=kwargs.pop("timeout", 15), **kwargs)
    response.raise_for_status()
    return response.json()


def latest_audit():
    try:
        items = api_json("/api/audits", params={"limit": 1, "audit_type": "readonly_health_audit"}).get("items", [])
        if not items:
            return None, None
        return items[0], api_json(f"/api/audits/{items[0]['audit_id']}")
    except requests.RequestException:
        return None, None


def signal(status, title, detail):
    st.markdown(f'<div class="signal {status}"><div class="signal-title">{title}</div><div class="signal-detail">{detail}</div></div>', unsafe_allow_html=True)


def render_nodes(nodes, connectivity):
    probe = {row.get("node_name"): row for row in connectivity}
    roles = {"C": "协调节点 · CN", "D": "数据节点 · DN", "G": "事务管理器 · GTM"}
    columns = st.columns(min(4, max(1, len(nodes))))
    for index, node in enumerate(nodes):
        state = probe.get(node.get("node_name"), {}).get("status", "unknown")
        label = {"reachable": "可达", "unreachable": "不可达", "unknown": "未知"}.get(state, "未知")
        state_class = {"reachable": "ok", "unreachable": "bad", "unknown": "unknown"}.get(state, "unknown")
        with columns[index % len(columns)]:
            st.markdown(f'<div class="node"><div class="node-top"><span class="node-name">{node.get("node_name")}</span><span class="state {state_class}">{label}</span></div><div class="node-role">{roles.get(node.get("node_type"), "数据库节点")}</div><div class="node-endpoint">{node.get("node_host")}:{node.get("node_port")}</div></div>', unsafe_allow_html=True)


def render_findings(findings, limit=5):
    if not findings:
        st.success("最近一次巡检没有规则告警")
        return
    for finding in findings[:limit]:
        severity = str(finding.get("severity", "unknown")).lower()
        st.markdown(f'<div class="finding"><div class="finding-top"><span class="finding-name">{finding.get("check", "巡检发现")}</span><span class="finding-sev {severity}">{severity}</span></div><div class="finding-detail">{finding.get("observed", "")}</div></div>', unsafe_allow_html=True)


def show_latest_ai(detail):
    evidence = (detail or {}).get("evidence") or {}
    analysis = (detail or {}).get("ai_analysis") or {}
    structured = analysis.get("structured") or {}
    st.markdown('<div class="section"><h3>最近一次 AI 结论</h3><span>证据已持久化，可从巡检记录继续调查</span></div>', unsafe_allow_html=True)
    if not detail:
        st.info("还没有巡检结果。先运行一次 AI 巡检，首页会显示根因、风险和建议。")
        return
    cols = st.columns([1, 3])
    with cols[0]:
        st.metric("风险等级", str(detail.get("risk_level", "unknown")).upper())
        st.caption(f"审计 · {detail.get('audit_id')}")
    with cols[1]:
        st.markdown(f"**根因判断**  \n{structured.get('root_cause') or '暂无根因判断'}")
        recommendations = structured.get("recommendations") or []
        if recommendations:
            st.markdown("**下一步建议**")
            for item in recommendations[:3]:
                st.markdown(f"- {item}")
    render_findings(evidence.get("findings") or [])


def run_audit(target=None):
    params = {"table": target} if target else None
    stages = {"starting": "启动巡检", "collecting": "采集数据库证据", "diagnosing": "AI 分析证据", "saving": "保存审计记录"}
    with st.status("正在启动巡检") as status:
        try:
            with requests.post(f"{API}/api/audits/health/stream", params=params, stream=True, timeout=config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS) as response:
                response.raise_for_status()
                for line in response.iter_lines(chunk_size=1):
                    if not line.startswith(b"data:"):
                        continue
                    event = json.loads(line[5:])
                    if event["type"] == "progress":
                        status.update(label=stages.get(event["stage"], event["stage"]))
                    elif event["type"] == "result":
                        st.session_state["last_audit"] = event["audit"]
                        status.update(label="巡检完成", state="complete")
                        break
                    elif event["type"] == "busy":
                        status.update(label="已有巡检正在运行", state="complete")
                        break
        except Exception as error:
            status.update(label="巡检失败", state="error")
            st.error(str(error))


if st.session_state.page == "overview":
    refresh_col, _ = st.columns([1, 6])
    with refresh_col:
        if st.button("刷新总览", use_container_width=True):
            st.rerun()
    with st.spinner("正在读取集群状态"):
        result = ClusterCollector(st.session_state.db).collect()
    if result.get("status") not in {"success", "partial"}:
        st.error("集群状态采集失败")
    else:
        data = result.get("data", {})
        nodes = data.get("nodes", [])
        connectivity = data.get("node_connectivity", [])
        online = sum(row.get("status") == "reachable" for row in connectivity)
        latest, detail = latest_audit()
        findings = ((detail or {}).get("evidence") or {}).get("findings") or []
        if result.get("status") == "partial" or any(row.get("status") == "unreachable" for row in connectivity):
            signal("partial", "集群需要关注", f"{online}/{len(nodes)} 个节点可达，采集结果可能不完整")
        else:
            signal("", "集群运行正常", f"{online}/{len(nodes)} 个注册节点可达，健康巡检持续运行")
        conn = data.get("connections", {})
        metrics = st.columns(4)
        metrics[0].metric("注册节点", f"{online}/{len(nodes)}")
        metrics[1].metric("CN 连接", f"{conn.get('total', 0)}/{conn.get('max_connections', '—')}", f"{conn.get('usage_percent', 0):.1f}%" if conn.get("usage_percent") is not None else None)
        metrics[2].metric("复制连接", len(data.get("replication", [])))
        metrics[3].metric("最近发现", len(findings), str(latest.get("risk_level", "unknown")).upper() if latest else "暂无记录")
        st.markdown('<div class="section"><h3>集群拓扑</h3><span>CN / DN / GTM 实时连通性</span></div>', unsafe_allow_html=True)
        render_nodes(nodes, connectivity)
        show_latest_ai(detail)
        left, right = st.columns(2)
        with left:
            st.markdown('<div class="section"><h3>值班操作</h3><span>直接进入核心工作流</span></div>', unsafe_allow_html=True)
            if st.button("运行 AI 巡检", type="primary", use_container_width=True, key="home-audit", on_click=go, args=("audit",)):
                pass
            if st.button("打开 Agent 助手", use_container_width=True, key="home-agent", on_click=go, args=("agent",)):
                pass
        with right:
            st.markdown('<div class="section"><h3>连接分布</h3><span>当前 CN 客户端会话</span></div>', unsafe_allow_html=True)
            st.table(conn.get("by_database", []))

elif st.session_state.page == "audit":
    automation = api_json("/api/automation/status")
    metrics = st.columns(3)
    metrics[0].metric("周期巡检", "运行中" if automation.get("automatic_health_audit_enabled") else "已关闭", f"每 {automation.get('interval_seconds', '—')} 秒")
    metrics[1].metric("最近计划状态", automation.get("latest_scheduled_collection_status") or "暂无")
    metrics[2].metric("自动修复", "已启用" if automation.get("automatic_repair_enabled") else "未启用")
    latest, detail = latest_audit()
    show_latest_ai(detail)
    with st.expander("高级范围：指定目标表", expanded=False):
        target = st.text_input("目标表", placeholder="public.orders", help="留空执行完整巡检。目标表只影响统计采集范围，不改变巡检的锁、连接和拓扑检查。")
    if st.button("运行一次 AI 巡检", type="primary", use_container_width=True):
        run_audit(target.strip() or None)
        st.rerun()
    current = st.session_state.get("last_audit")
    if current:
        st.markdown('<div class="section"><h3>本次巡检详情</h3><span>实时返回的 AI 结果</span></div>', unsafe_allow_html=True)
        show_latest_ai(current)
        with st.expander("查看完整证据与知识引用"):
            st.json({"evidence": current.get("evidence"), "knowledge_refs": current.get("knowledge_refs")})

elif st.session_state.page == "history":
    filters = st.columns(3)
    risk_label = filters[0].selectbox("风险", ["全部", "高与严重", "仅严重"])
    table = filters[1].text_input("目标表（筛选）", placeholder="public.orders")
    database = filters[2].text_input("数据库", placeholder="postgres")
    risk = {"全部": None, "高与严重": "high_or_critical", "仅严重": "critical"}[risk_label]
    items = api_json("/api/audits", params={"limit": 50, "risk": risk, "table": table or None, "database": database or None}).get("items", [])
    if items:
        rows = [{"时间": item.get("created_at"), "类型": item.get("audit_type"), "风险": str(item.get("risk_level", "unknown")).upper(), "采集": item.get("collection_status"), "发现": item.get("finding_count"), "引用": item.get("reference_count"), "审计 ID": item.get("audit_id")} for item in items]
        st.table(rows)
        options = {f"{item.get('created_at')} · {str(item.get('risk_level', 'unknown')).upper()} · {item.get('audit_id')}": item.get("audit_id") for item in items}
        selected = options[st.selectbox("打开一条审计", list(options))]
        show_latest_ai(api_json(f"/api/audits/{selected}"))
    else:
        st.info("没有符合筛选条件的巡检记录")

elif st.session_state.page == "repairs":
    queues = {"待审批": "pending", "待复核": "review", "全部": None}
    queue_label = st.selectbox("处理队列", list(queues))
    items = api_json("/api/repairs", params={"limit": 50, "queue": queues[queue_label]}).get("items", [])
    if items:
        counts = st.columns(4)
        for column, status, label in zip(counts, ["pending", "executing", "unverified", "failed"], ["待审批", "执行中", "待复核", "失败"]):
            column.metric(label, sum(item.get("status") == status for item in items))
        for item in items:
            label = {"pending": "待审批", "executing": "执行中", "unverified": "待复核", "failed": "失败", "executed": "已验证"}.get(item.get("status"), item.get("status"))
            with st.expander(f"{label} · {item.get('operation')} · {item.get('request_id')}"):
                st.write(item.get("reason") or "没有说明")
                st.json({"parameters": item.get("parameters"), "evidence": item.get("evidence")})
    else:
        st.success("当前没有待处理处置请求")

elif st.session_state.page == "agent":
    sessions = st.session_state.agent_sessions
    if not sessions:
        session_id = "session-1"
        sessions[session_id] = {"title": "新会话", "messages": []}
        st.session_state.active_agent_session = session_id
    if st.session_state.active_agent_session not in sessions:
        st.session_state.active_agent_session = next(iter(sessions))
    session_id = st.session_state.active_agent_session
    active_session = sessions[session_id]
    session_toolbar = st.columns([3, 1, 1])
    with session_toolbar[0]:
        session_options = list(sessions)
        selected_session = st.selectbox(
            "会话", session_options,
            index=session_options.index(session_id),
            format_func=lambda item: sessions[item]["title"],
            label_visibility="collapsed",
        )
        if selected_session != session_id:
            st.session_state.active_agent_session = selected_session
            st.rerun()
    with session_toolbar[1]:
        if st.button("新建会话", use_container_width=True, key="new-agent-session"):
            new_id = f"session-{len(sessions) + 1}"
            sessions[new_id] = {"title": "新会话", "messages": []}
            st.session_state.active_agent_session = new_id
            st.rerun()
    with session_toolbar[2]:
        if st.button("删除当前", use_container_width=True, key="delete-agent-session") and len(sessions) > 1:
            del sessions[session_id]
            st.session_state.active_agent_session = next(iter(sessions))
            st.rerun()

    active_messages = active_session["messages"]
    if not active_messages:
        st.markdown("#### 从一个运维问题开始")
        st.caption("Agent 会按需调用集群诊断、锁检查、知识库和 SQL 工具。")
    for message in active_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("trace"):
                with st.expander("工具调用记录"):
                    st.json(message["trace"])
    if prompt := st.chat_input("描述异常，或直接提出要检查的数据库问题…"):
        active_messages.append({"role": "user", "content": prompt})
        if active_session["title"] == "新会话":
            active_session["title"] = prompt[:24] + ("…" if len(prompt) > 24 else "")
        with st.chat_message("user"):
            st.markdown(prompt)
        try:
            history = [{"role": m["role"], "content": m["content"]} for m in active_messages[:-1]]
            response = requests.post(f"{API}/api/qa/ask", json={"question": prompt, "history": history}, timeout=900)
            response.raise_for_status()
            result = response.json()
            with st.chat_message("assistant"):
                st.markdown(result.get("answer", ""))
            active_messages.append({"role": "assistant", "content": result.get("answer", ""), "trace": result.get("tool_trace")})
            st.rerun()
        except Exception as error:
            st.error(str(error))
            active_messages.pop()

elif st.session_state.page == "performance":
    tabs = st.tabs(["锁等待", "长查询", "表统计"])
    with tabs[0]:
        if st.button("刷新锁信息", type="primary"):
            result = PerformanceCollector(st.session_state.db, config).collect().get("data", {})
            locks = result.get("locks", {})
            st.columns(2)[0].metric("总锁数", locks.get("total_locks", 0))
            st.columns(2)[1].metric("阻塞锁", locks.get("blocked_count", 0))
            st.table(locks.get("blocking_locks", []))
    with tabs[1]:
        st.caption("当前实例的活动视图可能在长查询期间返回 idle；完整语句会在服务端慢日志进入 AI 巡检。")
        if st.button("查询长查询", type="primary"):
            result = PerformanceCollector(st.session_state.db, config).collect().get("data", {})
            st.table(result.get("long_running_queries", []))
    with tabs[2]:
        if st.button("查询表统计", type="primary"):
            result = PerformanceCollector(st.session_state.db, config).collect().get("data", {})
            st.table(result.get("table_stats", []))

elif st.session_state.page == "sql":
    templates = {"选择模板": "", "查看连接": "SELECT datname, state, count(*) AS sessions FROM pg_catalog.pg_stat_activity GROUP BY datname, state ORDER BY sessions DESC;", "查看活动会话": "SELECT pid, usename, datname, application_name, state, wait_event_type, wait_event FROM pg_catalog.pg_stat_activity WHERE backend_type = 'client backend' ORDER BY state, pid;", "查看表统计": "SELECT schemaname, relname, n_live_tup, n_dead_tup FROM pg_catalog.pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 20;"}
    selected = st.selectbox("SQL 模板", list(templates))
    if selected != "选择模板" and st.button("载入模板"):
        st.session_state["sql_editor"] = templates[selected]
    sql_text = st.text_area("SQL 语句", height=220, key="sql_editor", placeholder="SELECT ...")
    explain = st.toggle("生成只读 EXPLAIN", value=True)
    if st.button("审核 SQL", type="primary", disabled=not sql_text.strip()):
        try:
            response = requests.post(f"{API}/api/sql-audit", json={"sql": sql_text, "explain": explain}, timeout=20)
            response.raise_for_status()
            report = response.json()
            st.metric("风险等级", {"critical": "严重", "high": "高", "medium": "中", "low": "低"}.get(report.get("risk_level"), "未知"))
            if report.get("findings"):
                st.table(report["findings"])
            if report.get("explain") is not None:
                st.json(report["explain"])
            if report.get("explain_error"):
                st.warning(report["explain_error"].get("message", "EXPLAIN 失败"))
        except Exception as error:
            st.error(str(error))
