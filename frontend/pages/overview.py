"""Cluster Overview Page - 集群总览"""
import streamlit as st
import requests
import html
from datetime import datetime

def render(db_connector, config):
    """Render cluster overview page"""

    # Page Header
    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 监控</div>
            <div class="page-title">集群总览</div>
            <div class="page-description">
                实时监控 OpenTenBase 分布式集群的拓扑结构、节点状态、连接使用情况和复制健康度
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Refresh button
    col1, col2, col3 = st.columns([1, 1, 6])
    with col1:
        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()

    # Collect data
    with st.spinner("正在采集集群数据..."):
        from backend.collectors.cluster import ClusterCollector
        collector = ClusterCollector(db_connector)
        result = collector.collect()

    if result['status'] == 'error':
        st.markdown("""
            <div class="alert-banner error">
                <div class="alert-icon">❌</div>
                <div class="alert-content">
                    <div class="alert-title">采集失败</div>
                    <div class="alert-message">无法连接到 OpenTenBase 集群或采集数据时出错</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        st.error(f"错误详情: {result.get('error', 'Unknown error')}")
        return

    data = result['data']
    nodes = data.get('nodes', [])
    connectivity = data.get('node_connectivity', [])
    connections = data.get('connections', {})
    replication = data.get('replication', [])

    # Health status banner
    online_nodes = sum(1 for item in connectivity if item.get('status') == 'reachable')
    total_nodes = len(nodes)

    if result['status'] == 'partial' or online_nodes < total_nodes:
        status_type = "warning"
        status_icon = "⚠️"
        status_title = "集群部分节点不可达"
        status_message = f"{online_nodes}/{total_nodes} 个节点在线，部分节点可能需要检查"
    else:
        status_type = "success"
        status_icon = "✅"
        status_title = "集群运行正常"
        status_message = f"所有 {total_nodes} 个注册节点网络可达，系统运行健康"

    st.markdown(f"""
        <div class="alert-banner {status_type}">
            <div class="alert-icon">{status_icon}</div>
            <div class="alert-content">
                <div class="alert-title">{status_title}</div>
                <div class="alert-message">{status_message}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Key Metrics
    conn_total = connections.get('total', 0)
    conn_max = connections.get('max_connections', 100)
    conn_usage = connections.get('usage_percent', 0)

    # Try to get latest audit info
    latest_audit_info = "暂无记录"
    finding_count = 0
    risk_level = "未知"

    try:
        api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"
        response = requests.get(
            f"{api_base}/api/audits",
            params={"limit": 1, "audit_type": "readonly_health_audit"},
            timeout=5
        )
        if response.ok:
            audits = response.json().get("items", [])
            if audits:
                latest = audits[0]
                latest_audit_info = latest.get('created_at', '未知时间')

                # Get detailed audit info
                detail_response = requests.get(f"{api_base}/api/audits/{latest['audit_id']}", timeout=5)
                if detail_response.ok:
                    detail = detail_response.json()
                    findings = detail.get('evidence', {}).get('findings', [])
                    finding_count = len(findings)
                    risk_level = latest.get('risk_level', '未知')
    except Exception as e:
        pass

    # Metrics Grid
    st.markdown(f"""
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">在线节点</div>
                <div class="metric-value">{online_nodes}<span style="font-size: 1.2rem; color: var(--text-tertiary);">/{total_nodes}</span></div>
                <div class="metric-change neutral">CN + DN + GTM 节点</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">客户端连接</div>
                <div class="metric-value">{conn_total}<span style="font-size: 1.2rem; color: var(--text-tertiary);">/{conn_max}</span></div>
                <div class="metric-change {'positive' if conn_usage < 70 else 'negative' if conn_usage > 85 else 'neutral'}">{conn_usage:.1f}% 使用率</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">复制连接</div>
                <div class="metric-value">{len(replication)}</div>
                <div class="metric-change neutral">主从复制会话</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最近巡检发现</div>
                <div class="metric-value">{finding_count}</div>
                <div class="metric-change {'positive' if finding_count == 0 else 'negative' if finding_count > 5 else 'neutral'}">风险等级: {risk_level}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Connection usage progress
    if conn_usage > 0:
        st.markdown('<div style="margin: 1rem 0;"><strong>CN 连接容量使用</strong></div>', unsafe_allow_html=True)
        st.progress(min(conn_usage / 100, 1.0), text=f"{conn_usage:.1f}% ({conn_total}/{conn_max})")

    # Node Topology Section
    st.markdown("""
        <div style="margin-top: 2rem;">
            <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem;">集群拓扑</h3>
            <p style="color: var(--text-secondary); font-size: 0.9rem;">分布式节点注册表和网络可达性</p>
        </div>
    """, unsafe_allow_html=True)

    if nodes:
        connectivity_map = {item.get('node_name'): item for item in connectivity}
        role_names = {"C": "CN 协调节点", "D": "DN 数据节点", "G": "GTM 事务管理器"}

        # Group nodes by type
        cn_nodes = [n for n in nodes if n.get('node_type') == 'C']
        dn_nodes = [n for n in nodes if n.get('node_type') == 'D']
        gtm_nodes = [n for n in nodes if n.get('node_type') == 'G']

        for node_type, node_list, type_label in [
            ('C', cn_nodes, '协调节点 (Coordinator)'),
            ('D', dn_nodes, '数据节点 (Data Node)'),
            ('G', gtm_nodes, '全局事务管理器 (GTM)')
        ]:
            if node_list:
                st.markdown(f'<div style="margin-top: 1.5rem; margin-bottom: 0.75rem; font-weight: 600; color: var(--text-secondary); font-size: 0.85rem;">{type_label}</div>', unsafe_allow_html=True)

                cols = st.columns(min(len(node_list), 4))
                for idx, node in enumerate(node_list):
                    with cols[idx % len(cols)]:
                        node_name = node.get('node_name', 'Unknown')
                        conn_info = connectivity_map.get(node_name, {})
                        is_online = conn_info.get('status') == 'reachable'

                        status_badge = f'<span class="status-badge {"online" if is_online else "offline"}"><span class="status-dot"></span>{"在线" if is_online else "离线"}</span>'

                        st.markdown(f"""
                            <div class="node-card">
                                <div class="node-header">
                                    <div class="node-name">{html.escape(node_name)}</div>
                                    {status_badge}
                                </div>
                                <div class="node-info">
                                    {html.escape(node.get('node_host', 'N/A'))}:{node.get('node_port', 'N/A')}
                                </div>
                            </div>
                        """, unsafe_allow_html=True)
    else:
        st.info("未发现注册节点")

    # Replication Status Section
    if replication:
        st.markdown("""
            <div style="margin-top: 2rem;">
                <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 1rem;">主从复制状态</h3>
            </div>
        """, unsafe_allow_html=True)

        repl_data = []
        for rep in replication:
            repl_data.append({
                "应用名称": rep.get('application_name', 'N/A'),
                "客户端地址": rep.get('client_addr', 'N/A'),
                "状态": rep.get('state', 'unknown'),
                "发送位置": rep.get('sent_lsn', 'N/A'),
                "写入位置": rep.get('write_lsn', 'N/A'),
                "同步状态": rep.get('sync_state', 'N/A'),
            })

        st.dataframe(repl_data, use_container_width=True, hide_index=True)
    else:
        st.markdown("""
            <div style="margin-top: 2rem;">
                <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 1rem;">主从复制状态</h3>
                <div class="alert-banner info">
                    <div class="alert-icon">ℹ️</div>
                    <div class="alert-content">
                        <div class="alert-message">当前 CN 未检测到活跃的复制连接</div>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    # Quick Actions
    st.markdown("""
        <div style="margin-top: 2.5rem;">
            <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 1rem;">快速操作</h3>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("🛡️ 运行健康巡检", use_container_width=True, type="primary"):
            st.session_state["navigation_page"] = "🛡️ AI 健康巡检"
            st.rerun()
    with col2:
        if st.button("🔍 性能诊断", use_container_width=True):
            st.session_state["navigation_page"] = "🔍 性能诊断"
            st.rerun()
    with col3:
        if st.button("💬 智能助手", use_container_width=True):
            st.session_state["navigation_page"] = "💬 智能助手"
            st.rerun()
    with col4:
        if st.button("📜 查看巡检历史", use_container_width=True):
            st.session_state["navigation_page"] = "📜 巡检历史"
            st.rerun()
