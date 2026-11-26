"""Performance Diagnostic Page - 性能诊断"""
import streamlit as st
import pandas as pd
from datetime import datetime

def render(db_connector, config):
    """Render performance diagnostic page"""

    # Page Header
    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 诊断</div>
            <div class="page-title">性能诊断</div>
            <div class="page-description">
                实时检测锁等待、长时间运行查询、表统计信息，快速定位性能瓶颈
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Tabs for different diagnostics
    tab1, tab2, tab3 = st.tabs(["🔒 锁分析", "⏱️ 长查询", "📊 表统计"])

    with tab1:
        render_lock_analysis(db_connector, config)

    with tab2:
        render_long_queries(db_connector, config)

    with tab3:
        render_table_statistics(db_connector, config)


def render_lock_analysis(db_connector, config):
    """Render lock analysis section"""

    st.markdown("### 🔒 锁等待分析")
    st.markdown("检测当前集群中的锁冲突、死锁和阻塞会话")

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_locks"):
            st.session_state.performance_lock_requested = True
            st.rerun()

    if not st.session_state.get("performance_lock_requested"):
        st.info("点击刷新后读取当前锁状态。页面打开时不会自动扫描数据库。")
        return
    with st.spinner("正在采集锁信息..."):
        from backend.collectors.performance import PerformanceCollector
        collector = PerformanceCollector(db_connector)
        result = collector.collect_locks()

    if result['status'] != 'success':
        st.error(f"采集失败: {result.get('error', result.get('errors', 'Unknown error'))}")
        return

    locks = result.get('data', {}).get('locks', [])

    if not locks:
        st.markdown("""
            <div class="alert-banner success">
                <div class="alert-icon">✅</div>
                <div class="alert-content">
                    <div class="alert-title">未检测到锁等待</div>
                    <div class="alert-message">当前没有会话在等待锁释放</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        return

    # Show lock statistics
    total_locks = len(locks)
    blocked_locks = sum(1 for lock in locks if not lock.get('granted', True))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总锁数量", total_locks)
    with col2:
        st.metric("阻塞的锁", blocked_locks)
    with col3:
        st.metric("活跃会话", len(set(lock.get('pid') for lock in locks)))

    # Show blocked locks
    if blocked_locks > 0:
        st.markdown("""
            <div class="alert-banner warning">
                <div class="alert-icon">⚠️</div>
                <div class="alert-content">
                    <div class="alert-title">检测到锁阻塞</div>
                    <div class="alert-message">有会话正在等待锁释放，可能影响性能</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    # Display locks table
    lock_data = []
    for lock in locks:
        lock_data.append({
            "PID": lock.get('pid'),
            "锁类型": lock.get('locktype', 'N/A'),
            "模式": lock.get('mode', 'N/A'),
            "已授予": "✅" if lock.get('granted') else "❌",
            "关系": lock.get('relation', 'N/A'),
            "查询": lock.get('query', 'N/A')[:100] + "..." if lock.get('query') and len(lock.get('query', '')) > 100 else lock.get('query', 'N/A')
        })

    st.dataframe(lock_data, use_container_width=True, hide_index=True)


def render_long_queries(db_connector, config):
    """Render long-running queries section"""

    st.markdown("### ⏱️ 长时间运行查询")
    st.markdown("检测执行时间超过阈值的查询，可能存在性能问题")

    col1, col2, col3 = st.columns([1, 2, 3])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_queries"):
            st.session_state.performance_query_requested = True
            st.rerun()

    with col2:
        threshold = st.number_input("时间阈值（秒）", min_value=1, max_value=3600, value=10, key="query_threshold")

    if not st.session_state.get("performance_query_requested"):
        st.info("点击刷新后读取当前长查询。完整慢语句由 AI 巡检的服务端慢日志链路识别。")
        return
    with st.spinner("正在采集查询信息..."):
        from backend.collectors.performance import PerformanceCollector
        collector = PerformanceCollector(db_connector)
        result = collector.collect_long_queries(threshold_seconds=threshold)

    if result['status'] != 'success':
        st.error(f"采集失败: {result.get('error', 'Unknown error')}")
        return

    queries = result.get('data', {}).get('queries', [])

    if not queries:
        st.markdown("""
            <div class="alert-banner success">
                <div class="alert-icon">✅</div>
                <div class="alert-content">
                    <div class="alert-title">未检测到长查询</div>
                    <div class="alert-message">当前没有超过阈值的查询在运行</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        return

    # Show query statistics
    st.markdown(f"""
        <div class="alert-banner warning">
            <div class="alert-icon">⚠️</div>
            <div class="alert-content">
                <div class="alert-title">检测到 {len(queries)} 个长查询</div>
                <div class="alert-message">这些查询执行时间超过 {threshold} 秒</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Display queries
    for idx, query in enumerate(queries, 1):
        with st.expander(f"查询 #{idx} - PID: {query.get('pid')} - 运行时长: {query.get('duration', 'N/A')}"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**PID**: {query.get('pid')}")
                st.markdown(f"**用户**: {query.get('usename', 'N/A')}")
                st.markdown(f"**数据库**: {query.get('datname', 'N/A')}")
            with col2:
                st.markdown(f"**状态**: {query.get('state', 'N/A')}")
                st.markdown(f"**开始时间**: {query.get('query_start', 'N/A')}")
                st.markdown(f"**运行时长**: {query.get('duration', 'N/A')}")

            st.markdown("**查询语句**:")
            st.code(query.get('query', 'N/A'), language="sql")


def render_table_statistics(db_connector, config):
    """Render table statistics section"""

    st.markdown("### 📊 表统计信息")
    st.markdown("查看表的大小、行数、索引使用情况和最后 ANALYZE 时间")

    col1, col2, col3 = st.columns([1, 2, 3])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_stats"):
            st.session_state.performance_stats_requested = True
            st.rerun()

    with col2:
        limit = st.number_input("显示表数量", min_value=10, max_value=500, value=50, key="table_limit")

    if not st.session_state.get("performance_stats_requested"):
        st.info("点击刷新后读取表统计信息。")
        return
    with st.spinner("正在采集表统计信息..."):
        from backend.collectors.performance import PerformanceCollector
        collector = PerformanceCollector(db_connector)
        result = collector.collect_table_stats(limit=limit)

    if result['status'] != 'success':
        st.error(f"采集失败: {result.get('error', 'Unknown error')}")
        return

    tables = result.get('data', {}).get('tables', [])

    if not tables:
        st.info("未找到表统计信息")
        return

    # Show summary
    total_size = sum(table.get('total_size_bytes', 0) for table in tables)
    total_rows = sum(table.get('n_live_tup', 0) for table in tables)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("表节点统计数", len(tables))
    with col2:
        st.metric("总大小", f"{total_size / (1024**3):.2f} GB")
    with col3:
        st.metric("节点估算行数汇总", f"{total_rows:,}")

    # Display table data
    table_data = []
    for table in tables:
        table_data.append({
            "节点": table.get('node_name', '—'),
            "Schema": table.get('schemaname', 'N/A'),
            "表名": table.get('tablename', 'N/A'),
            "行数": f"{table.get('n_live_tup', 0):,}",
            "表大小": f"{table.get('table_size_bytes', 0) / (1024**2):.2f} MB",
            "索引大小": f"{table.get('indexes_size_bytes', 0) / (1024**2):.2f} MB",
            "总大小": f"{table.get('total_size_bytes', 0) / (1024**2):.2f} MB",
            "最后 ANALYZE": table.get('last_analyze', 'N/A')
        })

    st.dataframe(table_data, use_container_width=True, hide_index=True)

    # Highlight stale statistics
    stale_tables = [t for t in tables if t.get('last_analyze') is None or t.get('last_analyze') == 'N/A']
    if stale_tables:
        st.markdown("""
            <div class="alert-banner warning">
                <div class="alert-icon">⚠️</div>
                <div class="alert-content">
                    <div class="alert-title">发现统计信息过期的表</div>
                    <div class="alert-message">建议对这些表运行 ANALYZE 以更新优化器统计信息</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
