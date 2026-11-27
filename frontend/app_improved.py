"""OpenTenBase AIOps - Improved Streamlit Application with Distributed Support"""
import streamlit as st
import sys
import os
from api_client import requests
import json
from pathlib import Path
from datetime import datetime

# Add backend to path
backend_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_path))

from backend.utils.config import Config
from backend.utils.db_connector import OpenTenBaseConnector
from backend.utils.distributed_collector import DistributedCollector
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

# Custom CSS - improved to prevent flickering
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
    /* Prevent dataframe flickering */
    .stDataFrame {
        min-height: 300px;
    }
    .stDataFrame table {
        border-collapse: collapse;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'config' not in st.session_state:
    st.session_state.config = Config()

if 'db_connector' not in st.session_state:
    st.session_state.db_connector = OpenTenBaseConnector(st.session_state.config)

if 'distributed_collector' not in st.session_state:
    st.session_state.distributed_collector = DistributedCollector(st.session_state.config)

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
        ["📊 健康监控", "🌐 分布式采集", "🛡️ 只读巡检", "📜 巡检历史", "🧾 修复审批", "💬 智能问答", "🔍 性能诊断"],
        label_visibility="collapsed"
    )

    st.markdown("---")

    # Connection status
    st.markdown("### 连接状态")

    if st.button("测试连接", use_container_width=True, key="test-connection-btn"):
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
    st.caption(f"**分布式**: {'✅' if st.session_state.config.AIOPS_DISTRIBUTED_ENABLED else '❌'}")

    st.markdown("---")
    st.caption("OpenTenBase AIOps v0.2.0")


# Main content
if page == "📊 健康监控":
    st.markdown('<div class="main-header">📊 集群健康监控</div>', unsafe_allow_html=True)

    # Refresh button
    col1, col2, col3 = st.columns([5, 1, 1])
    with col2:
        if st.button("🔄 刷新", use_container_width=True, key="refresh-health-btn"):
            st.rerun()
    with col3:
        all_nodes = st.checkbox("全集群", value=False, key="health-all-nodes")

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

        # Nodes information - with key to prevent flickering
        st.markdown("### 集群节点")
        nodes = data.get('nodes', [])
        if nodes:
            st.dataframe(
                nodes,
                use_container_width=True,
                hide_index=True,
                key="nodes-table"
            )
        else:
            st.info("暂无节点信息")

        # Node connectivity
        connectivity = data.get('node_connectivity', [])
        if connectivity:
            st.markdown("#### 节点网络连通性")
            st.dataframe(
                connectivity,
                use_container_width=True,
                hide_index=True,
                key="connectivity-table"
            )

        # Connection details
        st.markdown("### 连接详情")
        connections = conn_info.get('by_database', [])
        if connections:
            st.dataframe(
                connections,
                use_container_width=True,
                hide_index=True,
                key="connections-table"
            )
        else:
            st.info("暂无连接信息")

        # Replication status
        st.markdown("### 复制状态")
        replication = data.get('replication', [])
        if replication:
            st.dataframe(
                replication,
                use_container_width=True,
                hide_index=True,
                key="replication-table"
            )
        else:
            st.info("暂无复制信息")
    else:
        st.error(f"采集失败: {result.get('error', '未知错误')}")


elif page == "🌐 分布式采集":
    st.markdown('<div class="main-header">🌐 分布式采集</div>', unsafe_allow_html=True)

    if not st.session_state.config.AIOPS_DISTRIBUTED_ENABLED:
        st.error("❌ 分布式采集已禁用，请在配置中启用")
        st.stop()

    st.markdown("### 集群节点")

    # Get available nodes
    with st.spinner("正在加载节点列表..."):
        try:
            nodes = st.session_state.distributed_collector.get_cluster_nodes()
            st.success(f"✅ 已发现 {len(nodes)} 个节点")
        except Exception as e:
            st.error(f"❌ 节点发现失败: {e}")
            st.stop()

    # Display nodes in columns
    col1, col2 = st.columns([2, 3])

    with col1:
        st.markdown("#### 可用节点")
        node_names = [f"[{n['node_type']}] {n['node_name']}" for n in nodes]
        st.dataframe(
            [{"节点": name, "类型": n["node_type"]} for name, n in zip(node_names, nodes)],
            use_container_width=True,
            hide_index=True,
            key="nodes-list"
        )

    with col2:
        st.markdown("#### 节点详情")
        st.dataframe(
            nodes,
            use_container_width=True,
            hide_index=True,
            key="nodes-detail"
        )

    st.markdown("---")

    # SQL Query section
    st.markdown("### 自定义查询")

    col1, col2 = st.columns([3, 1])
    with col1:
        sql_query = st.text_area(
            "输入 SQL 查询",
            value="SELECT current_database() as db, version() as version",
            height=100,
            key="distributed-sql-query"
        )
    with col2:
        st.markdown("")  # Spacing
        node_filter = st.radio(
            "节点过滤",
            ["全部", "协调节点 (C)", "数据节点 (D)"],
            key="distributed-node-filter"
        )

    # Map filter
    filter_map = {"全部": None, "协调节点 (C)": "C", "数据节点 (D)": "D"}

    if st.button("执行查询", use_container_width=True, key="distributed-execute-btn"):
        with st.spinner("正在执行分布式查询..."):
            try:
                result = st.session_state.distributed_collector.collect_from_all_nodes(
                    sql_query,
                    node_filter=filter_map[node_filter]
                )

                # Display summary
                summary = result['summary']
                st.markdown("### 执行结果")

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("总节点数", summary['total_nodes'])
                with col2:
                    st.metric("成功", summary['success'], delta=f"{summary['failed']} 失败")
                with col3:
                    if summary['total_nodes'] > 0:
                        success_rate = round(summary['success'] / summary['total_nodes'] * 100, 1)
                        st.metric("成功率", f"{success_rate}%")

                # Display results by node
                st.markdown("#### 按节点结果")
                for result_item in result['results']:
                    with st.expander(
                        f"✅ {result_item['node_name']} [{result_item['node_type']}] - {result_item['row_count']} 行",
                        expanded=False,
                        key=f"result-{result_item['node_name']}"
                    ):
                        st.dataframe(
                            result_item['data'],
                            use_container_width=True,
                            hide_index=True,
                            key=f"result-data-{result_item['node_name']}"
                        )

                # Display errors if any
                if result['errors']:
                    st.markdown("#### 错误")
                    st.dataframe(
                        result['errors'],
                        use_container_width=True,
                        hide_index=True,
                        key="result-errors"
                    )

            except Exception as e:
                st.error(f"执行失败: {e}")
                logger.exception("Distributed query failed")


# Placeholder for other pages (keep existing code)
elif page == "🛡️ 只读巡检":
    st.markdown('<div class="main-header">🛡️ 只读健康巡检</div>', unsafe_allow_html=True)
    st.info("此页面保留原有功能，待后续更新...")

elif page == "📜 巡检历史":
    st.markdown('<div class="main-header">📜 巡检历史</div>', unsafe_allow_html=True)
    st.info("此页面保留原有功能，待后续更新...")

elif page == "🧾 修复审批":
    st.markdown('<div class="main-header">🧾 修复审批</div>', unsafe_allow_html=True)
    st.info("此页面保留原有功能，待后续更新...")

elif page == "💬 智能问答":
    st.markdown('<div class="main-header">💬 智能问答</div>', unsafe_allow_html=True)
    st.info("此页面保留原有功能，待后续更新...")

elif page == "🔍 性能诊断":
    st.markdown('<div class="main-header">🔍 性能诊断</div>', unsafe_allow_html=True)
    st.info("此页面保留原有功能，待后续更新...")
