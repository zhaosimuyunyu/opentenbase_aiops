"""Audit History Page - 巡检历史"""
import streamlit as st
import requests
from datetime import datetime

def render(config):
    """Render audit history page"""

    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 记录</div>
            <div class="page-title">巡检历史</div>
            <div class="page-description">
                查看所有历史巡检记录、风险发现趋势和可追溯的诊断依据
            </div>
        </div>
    """, unsafe_allow_html=True)

    api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"

    # Filters
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        risk_filter = st.selectbox(
            "风险等级过滤",
            ["全部", "高风险", "中等风险", "低风险", "无风险"],
            key="history_risk_filter"
        )
    with col2:
        limit = st.selectbox("每页条数", [10, 20, 50], index=0, key="history_limit")
    with col3:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    risk_map = {"全部": None, "高风险": "high", "中等风险": "medium", "低风险": "low", "无风险": "none"}
    risk_param = risk_map[risk_filter]

    # Fetch audits
    try:
        params = {"limit": limit, "audit_type": "readonly_health_audit"}
        if risk_param:
            params["risk"] = "high_or_critical" if risk_param == "high" else None

        response = requests.get(f"{api_base}/api/audits", params=params, timeout=10)

        if not response.ok:
            st.error(f"加载失败: {response.status_code} — 请确认 API 服务已启动")
            return

        data = response.json()
        audits = data.get("items", [])
        total = data.get("total", len(audits))

    except requests.ConnectionError:
        st.error("无法连接到 API 服务 (http://aiops-api:8000)")
        return
    except Exception as e:
        st.error(f"请求失败: {str(e)}")
        return

    if not audits:
        st.markdown("""
            <div class="alert-banner info">
                <div class="alert-icon">ℹ️</div>
                <div class="alert-content">
                    <div class="alert-title">暂无巡检记录</div>
                    <div class="alert-message">前往「AI 健康巡检」页面运行第一次巡检</div>
                </div>
            </div>
        """, unsafe_allow_html=True)
        return

    # Summary metrics
    high_count   = sum(1 for a in audits if a.get('risk_level') == 'high')
    medium_count = sum(1 for a in audits if a.get('risk_level') == 'medium')
    low_count    = sum(1 for a in audits if a.get('risk_level') in ('low', 'none'))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总计巡检次数", total)
    col2.metric("高风险次数",   high_count)
    col3.metric("中等风险次数", medium_count)
    col4.metric("低/无风险次数", low_count)

    st.markdown("---")

    # Audit list
    for audit in audits:
        audit_id   = audit.get('audit_id', 'unknown')
        created_at = audit.get('created_at', 'unknown')
        risk_level = audit.get('risk_level', 'unknown')
        audit_type = audit.get('audit_type', 'unknown')
        reason     = audit.get('reason', '')

        risk_badge_map = {
            'high':   ('<span style="color:var(--error);font-weight:700;">🚨 高风险</span>',   'error'),
            'medium': ('<span style="color:var(--warning);font-weight:700;">⚠️ 中等风险</span>', 'warning'),
            'low':    ('<span style="color:var(--info);font-weight:700;">ℹ️ 低风险</span>',    'info'),
            'none':   ('<span style="color:var(--success);font-weight:700;">✅ 无风险</span>',  'success'),
        }
        risk_badge, risk_color = risk_badge_map.get(risk_level, (f'<span>{risk_level}</span>', 'info'))

        with st.expander(f"📋 {created_at}  |  {risk_badge}  |  {reason[:60] if reason else audit_id}", expanded=False):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**巡检 ID**: `{audit_id}`")
                st.markdown(f"**类型**: {audit_type}")
                st.markdown(f"**原因**: {reason or '—'}")
            with col_b:
                st.markdown(f"**时间**: {created_at}")
                st.markdown(f"**风险等级**: {risk_level}")

            # Load detail on demand
            if st.button("📄 加载详情", key=f"load_{audit_id}"):
                with st.spinner("加载中..."):
                    try:
                        detail_resp = requests.get(
                            f"{api_base}/api/audits/{audit_id}", timeout=15
                        )
                        if detail_resp.ok:
                            detail = detail_resp.json()
                            evidence = detail.get('evidence', {})
                            findings = evidence.get('findings', [])

                            if findings:
                                st.markdown(f"**发现 {len(findings)} 个问题：**")
                                for finding in findings:
                                    sev = finding.get('severity', 'low')
                                    sev_icon = {'high': '🚨', 'medium': '⚠️', 'low': 'ℹ️'}.get(sev, '•')
                                    st.markdown(
                                        f"{sev_icon} **{finding.get('check', 'unknown')}**: "
                                        f"{finding.get('observed', '')}"
                                    )
                            else:
                                st.success("本次巡检未发现问题")

                            analysis = detail.get('analysis', {})
                            structured = (analysis or {}).get('structured', {})
                            if structured.get('summary'):
                                st.markdown("**AI 摘要:**")
                                st.write(structured['summary'])

                        else:
                            st.error(f"加载失败: {detail_resp.status_code}")
                    except Exception as e:
                        st.error(f"加载详情失败: {str(e)}")
