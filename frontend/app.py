"""OpenTenBase AIOps - Main Streamlit Application"""
import streamlit as st
import sys
import asyncio
import os
import requests
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
from backend.engines.readonly_audit_engine import ReadonlyAuditEngine

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
        ["📊 健康监控", "🛡️ 只读巡检", "📜 巡检历史", "💬 智能问答", "🔍 性能诊断"],
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

    if result['status'] == 'success':
        data = result['data']

        # Overview metrics
        st.markdown("### 总览")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            node_count = len(data.get('nodes', []))
            st.metric("集群节点", f"{node_count}", help="当前活跃的集群节点数")

        with col2:
            conn_info = data.get('connections', {})
            conn_total = conn_info.get('total', 0)
            conn_max = conn_info.get('max_connections', 0)
            st.metric(
                "活跃连接",
                f"{conn_total}/{conn_max}",
                f"{conn_info.get('usage_percent', 0):.1f}%"
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
    if st.button("运行只读巡检", type="primary"):
        with st.spinner("正在采集 OpenTenBase 状态并分析..."):
            try:
                audit = asyncio.run(ReadonlyAuditEngine().run_health_audit())
                st.session_state.last_health_audit = audit
            except Exception as error:
                st.error(f"巡检失败: {error}")
    audit = st.session_state.get("last_health_audit")
    if audit:
        st.metric("风险等级", audit["risk_level"])
        st.caption(f"审计 ID: {audit['audit_id']}")
        findings = audit.get("findings", [])
        if findings:
            st.dataframe(findings, use_container_width=True, hide_index=True)
        else:
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
        history = requests.get(f"{api_base}/api/audits", params={"limit": 50}, timeout=10).json()
        items = history.get("items", [])
        if items:
            st.dataframe(items, use_container_width=True, hide_index=True)
            selected_id = st.selectbox(
                "查看审计详情",
                [item["audit_id"] for item in items],
                format_func=lambda value: next(
                    item["audit_type"] + " · " + item["created_at"] for item in items
                    if item["audit_id"] == value
                ),
            )
            if selected_id:
                detail = requests.get(f"{api_base}/api/audits/{selected_id}", timeout=10).json()
                st.json(detail.get("ai_analysis", {}))
                with st.expander("查看现场证据"):
                    st.json(detail.get("evidence", {}))
        else:
            st.info("暂无巡检记录")
    except Exception as error:
        st.error(f"读取巡检历史失败: {error}")

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
