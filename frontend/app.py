"""OpenTenBase AIOps - Main Streamlit Application"""
import streamlit as st
import sys
import os
import requests
import json
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

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .status-success {
        color: #28a745;
    }
    .status-warning {
        color: #ffc107;
    }
    .status-error {
        color: #dc3545;
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

# Sidebar
with st.sidebar:
    st.markdown("# 🤖 OpenTenBase AIOps")
    st.markdown("---")

    # Navigation
    page = st.radio(
        "导航",
        ["📊 健康监控", "🛡️ 只读巡检", "📜 巡检历史", "🧾 修复审批", "💬 智能问答", "🔍 性能诊断"],
        label_visibility="collapsed"
    )

    st.markdown("---")

    # Connection status
    st.markdown("### 连接状态")

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

    # System info
    st.markdown("### 系统信息")
    st.caption(f"**主机**: {st.session_state.config.DB_HOST}")
    st.caption(f"**端口**: {st.session_state.config.DB_PORT}")
    st.caption(f"**模型**: {st.session_state.config.DEEPSEEK_MODEL}")

    st.markdown("---")
    st.caption("OpenTenBase AIOps v0.1.0")

def render_analysis_status(analysis):
    if not isinstance(analysis, dict):
        return
    tool_errors = set(analysis.get("tool_errors") or [])
    tool_trace = analysis.get("tool_trace") or []
    if tool_trace:
        with st.expander("诊断工具调用"):
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


# Main content
if page == "📊 健康监控":
    st.markdown('<div class="main-header">📊 集群健康监控</div>', unsafe_allow_html=True)

    # Refresh button
    col1, col2 = st.columns([6, 1])
    with col2:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    st.markdown("---")

    # Collect data
    with st.spinner("正在采集数据..."):
        collector = ClusterCollector(st.session_state.db_connector)
        result = collector.collect()

    if result['status'] in {'success', 'partial'}:
        data = result['data']
        if result['status'] == 'partial':
            st.warning("集群状态仅部分可用，请检查下方节点连通性和采集错误。")
            if result.get('errors'):
                with st.expander("查看采集错误"):
                    st.json(result['errors'])

        # Overview metrics
        st.markdown("### 总览")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            node_count = len(data.get('nodes', []))
            st.metric("集群节点", f"{node_count}", help="当前活跃的集群节点数")

        with col2:
            conn_info = data.get('connections', {})
            conn_total = conn_info.get('total')
            conn_max = conn_info.get('max_connections')
            usage = conn_info.get('usage_percent')
            st.metric(
                "当前 CN 客户端连接",
                f"{conn_total}/{conn_max} ({usage:.1f}%)" if usage is not None else "未知",
            )

        with col3:
            repl_count = len(data.get('replication', []))
            st.metric("复制连接", f"{repl_count}", help="主从复制连接数")

        with col4:
            is_replica = data.get('database_info', {}).get('is_replica', False)
            role = "备库" if is_replica else "主库"
            st.metric("节点角色", role)

        st.markdown("---")

        # Nodes information
        st.markdown("### 集群节点")
        nodes = data.get('nodes', [])
        if nodes:
            st.dataframe(nodes, use_container_width=True, hide_index=True)
        else:
            st.info("暂无节点信息")
        connectivity = data.get('node_connectivity', [])
        if connectivity:
            st.markdown("#### 节点网络连通性")
            st.dataframe(connectivity, use_container_width=True, hide_index=True)

        # Connection details
        st.markdown("### 连接详情")
        connections = conn_info.get('by_database', [])
        if connections:
            st.dataframe(connections, use_container_width=True, hide_index=True)
        else:
            st.info("暂无连接信息")

        # Replication status
        st.markdown("### 复制状态")
        replication = data.get('replication', [])
        if replication:
            st.dataframe(replication, use_container_width=True, hide_index=True)
        else:
            st.info("暂无复制信息（可能是主库无从库，或当前查询的是从库）")

        # AI Health Summary
        st.markdown("---")
        st.markdown("### 🤖 AI 健康评估")

        if st.button("生成健康报告", use_container_width=True):
            if st.session_state.llm_client:
                with st.spinner("AI 正在分析..."):
                    try:
                        perf_collector = PerformanceCollector(
                            st.session_state.db_connector,
                            st.session_state.config
                        )
                        perf_data = perf_collector.collect().get('data', {})

                        summary = st.session_state.llm_client.generate_health_summary(
                            cluster_data=data,
                            performance_data=perf_data
                        )
                        st.markdown(summary)
                    except Exception as e:
                        st.error(f"生成报告失败: {e}")
            else:
                st.warning("LLM 客户端未初始化，请检查 API 配置")

    else:
        st.error(f"数据采集失败: {result.get('error', 'unknown')}")

elif page == "🛡️ 只读巡检":
    st.markdown('<div class="main-header">🛡️ AI 只读健康巡检</div>', unsafe_allow_html=True)
    st.caption("只采集数据库状态并生成诊断，不执行终止会话、修改参数或其他写操作。")
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        automation = requests.get(f"{api_base}/api/automation/status", timeout=10).json()
        mode = "已启用" if automation["automatic_health_audit_enabled"] else "已关闭"
        st.caption(f"周期巡检{mode} · 间隔 {automation['interval_seconds']} 秒")
    except Exception as error:
        st.warning(f"读取周期巡检状态失败: {error}")
    statistics_target = st.text_input("目标表（可选）", placeholder="public.orders").strip()
    if st.button("运行只读巡检", type="primary"):
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
        st.metric("风险等级", audit["risk_level"])
        evidence = audit.get("evidence") or {}
        render_collection_status(evidence)
        render_analysis_status(audit)
        st.caption(f"审计 ID: {audit['audit_id']}")
        findings = audit.get("findings", [])
        if findings:
            rows = [
                {**finding, "evidence": json.dumps(finding.get("evidence"), ensure_ascii=False)}
                for finding in findings
            ]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            render_repair_proposal(api_base, audit["audit_id"], findings)
        elif evidence.get("collection_status") == "success":
            st.success("未发现规则告警")
        structured = audit.get("structured") or {}
        if structured.get("root_cause"):
            st.markdown("### AI 判断")
            st.write(structured["root_cause"])
        recommendations = structured.get("recommendations") or []
        if recommendations:
            st.markdown("### 只读复核建议")
            for recommendation in recommendations:
                st.markdown(f"- {recommendation}")
        with st.expander("查看现场证据"):
            st.json(audit.get("evidence", {}))
        with st.expander("查看知识引用"):
            st.dataframe(audit.get("knowledge_refs", []), use_container_width=True, hide_index=True)

elif page == "📜 巡检历史":
    st.markdown('<div class="main-header">📜 巡检历史</div>', unsafe_allow_html=True)
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        risks = {"全部": None, "高与严重": "high_or_critical", "仅严重": "critical"}
        risk = risks[st.selectbox("风险等级筛选", list(risks))]
        table_filter = st.text_input("目标表筛选", placeholder="public.orders").strip()
        database_filter = st.text_input("数据库筛选", placeholder="postgres").strip()
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
            st.dataframe(items, use_container_width=True, hide_index=True)
            audit_options = {
                f"{item.get('database') or '未知数据库'} · {item['audit_type']} · "
                f"{item['created_at']} · {item['audit_id']}": item["audit_id"]
                for item in items
            }
            selected_id = audit_options[st.selectbox("查看审计详情", list(audit_options))]
            if selected_id:
                response = requests.get(f"{api_base}/api/audits/{selected_id}", timeout=10)
                response.raise_for_status()
                detail = response.json()
                evidence = detail.get("evidence") or {}
                render_collection_status(evidence)
                render_repair_proposal(api_base, selected_id, evidence.get("findings", []))
                render_analysis_status(detail.get("ai_analysis"))
                st.json(detail.get("ai_analysis", {}))
                with st.expander("查看现场证据"):
                    st.json(detail.get("evidence", {}))
                with st.expander("查看知识引用"):
                    st.json(detail.get("knowledge_refs") or [])
        else:
            st.info("暂无符合筛选条件的巡检记录")
    except Exception as error:
        st.error(f"读取巡检历史失败: {error}")

elif page == "🧾 修复审批":
    st.markdown('<div class="main-header">🧾 修复审批</div>', unsafe_allow_html=True)
    api_base = os.getenv("AIOPS_API_URL", "http://aiops-api:8000")
    try:
        queues = {"待审批": "pending", "待复核": "review", "全部记录": None}
        queue = queues[st.selectbox("请求范围", list(queues))]
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
        for item in items:
            with st.expander(f"{item['status']} · {item['operation']} · {item['request_id']}"):
                proposal_evidence = item.get("evidence") or {}
                model_review = proposal_evidence.get("model_review") or {}
                program_review = proposal_evidence.get("program_review") or {}
                ready = program_review.get("approved") is True and model_review.get("approved") is True
                if ready:
                    st.caption("程序校验通过 · Agent 复核通过")
                    if model_review.get("reason"):
                        st.text(model_review["reason"])
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
                elif item["status"] == "failed":
                    st.error("修复执行失败")
                if item.get("result") is not None:
                    st.write("已保存的处置结果")
                    st.json(item["result"])
                if item.get("manual_review"):
                    st.write("人工复核记录")
                    st.json(item["manual_review"])
                elif item["status"] in {"executing", "unverified"}:
                    with st.form(f"review-{item['request_id']}"):
                        note = st.text_area("复核结论与依据", max_chars=4000)
                        review_token = st.text_input("审批令牌", type="password")
                        if st.form_submit_button("保存复核记录"):
                            response = requests.post(
                                f"{api_base}/api/repairs/{item['request_id']}/manual-review",
                                json={"note": note, "token": review_token}, timeout=10,
                            )
                            if response.ok:
                                st.rerun()
                            st.error(response.text)
                if item["status"] == "pending":
                    if not ready:
                        st.warning("待补审。请从原始巡检重新提交修复提案。")
                    approver = st.session_state.config.AIOPS_APPROVER_ID
                    token = st.text_input("审批令牌", type="password", key=f"t-{item['request_id']}")
                    left, right = st.columns(2)
                    if left.button("批准并执行", key=f"approve-{item['request_id']}", disabled=not ready):
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
                    reject_reason = right.text_input("拒绝原因", key=f"r-{item['request_id']}")
                    if right.button("拒绝", key=f"reject-{item['request_id']}"):
                        response = requests.post(f"{api_base}/api/repairs/{item['request_id']}/reject", json={"approver": approver, "reason": reject_reason, "token": token}, timeout=10)
                        if response.ok:
                            st.session_state.repair_decision = response.json()
                            st.rerun()
                        st.error(response.text)
    except Exception as error:
        st.error(f"读取修复审批失败: {error}")

elif page == "💬 智能问答":
    st.markdown('<div class="main-header">💬 智能问答助手</div>', unsafe_allow_html=True)
    st.markdown("向 AI 助手提问关于 OpenTenBase 的问题")
    st.markdown("---")

    # Initialize chat history
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("输入您的问题..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Generate response
        with st.chat_message("assistant"):
            if st.session_state.llm_client:
                with st.spinner("思考中..."):
                    try:
                        # Collect context
                        collector = ClusterCollector(st.session_state.db_connector)
                        cluster_data = collector.collect().get('data', {})

                        context = f"""
当前集群状态：
- 节点数: {len(cluster_data.get('nodes', []))}
- 连接数: {cluster_data.get('connections', {}).get('total', 'unknown')}
- 复制状态: {len(cluster_data.get('replication', []))} 个复制连接
"""

                        response = st.session_state.llm_client.answer_question(
                            question=prompt,
                            context=context
                        )

                        st.markdown(response)
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": response
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

    # Clear chat button
    if st.session_state.messages:
        if st.button("清空对话", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

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
