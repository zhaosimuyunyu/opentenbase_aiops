"""Repair Center Page - 修复中心"""
import streamlit as st
from api_client import requests

def render(config):
    """Render repair center page"""

    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 运维</div>
            <div class="page-title">修复中心</div>
            <div class="page-description">
                复核待处理的修复建议，查看执行状态与验证结果，管理运维操作审批流程
            </div>
        </div>
    """, unsafe_allow_html=True)

    api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"

    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📋 待审批", "⏳ 执行中", "✅ 已完成"])

    with tab1:
        render_pending_repairs(api_base, config)

    with tab2:
        render_running_repairs(api_base, config)

    with tab3:
        render_completed_repairs(api_base, config)


def render_pending_repairs(api_base, config):
    """Render pending repair requests"""

    st.markdown("### 📋 待审批的修复请求")

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_pending"):
            st.rerun()

    try:
        response = requests.get(
            f"{api_base}/api/repairs",
            params={"queue": "pending"},
            timeout=10
        )

        if not response.ok:
            st.error(f"加载失败: {response.status_code}")
            return

        repairs = response.json().get("items", [])

        if not repairs:
            st.markdown("""
                <div class="alert-banner info">
                    <div class="alert-icon">ℹ️</div>
                    <div class="alert-content">
                        <div class="alert-title">暂无待审批请求</div>
                        <div class="alert-message">当前没有等待人工审批的修复操作</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            return

        for repair in repairs:
            render_repair_card(repair, api_base, config, show_approve=True)

    except Exception as e:
        st.error(f"加载失败: {str(e)}")


def render_running_repairs(api_base, config):
    """Render running repair requests"""

    st.markdown("### ⏳ 执行中的修复任务")

    col1, col2 = st.columns([1, 5])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_running"):
            st.rerun()

    try:
        response = requests.get(
            f"{api_base}/api/repairs",
            params={"queue": "review"},
            timeout=10
        )

        if not response.ok:
            st.error(f"加载失败: {response.status_code}")
            return

        repairs = response.json().get("items", [])

        if not repairs:
            st.info("当前没有正在执行的修复任务")
            return

        for repair in repairs:
            render_repair_card(repair, api_base, config, show_approve=False)

    except Exception as e:
        st.error(f"加载失败: {str(e)}")


def render_completed_repairs(api_base, config):
    """Render completed repair requests"""

    st.markdown("### ✅ 已完成的修复记录")

    col1, col2, col3 = st.columns([1, 2, 3])
    with col1:
        if st.button("🔄 刷新", use_container_width=True, key="refresh_completed"):
            st.rerun()
    with col2:
        limit = st.selectbox("显示数量", [10, 20, 50], key="completed_limit")

    try:
        response = requests.get(
            f"{api_base}/api/repairs",
            params={"limit": limit},
            timeout=10
        )

        if not response.ok:
            st.error(f"加载失败: {response.status_code}")
            return

        repairs = response.json().get("items", [])

        if not repairs:
            st.info("暂无完成的修复记录")
            return

        # Statistics
        executed = sum(1 for r in repairs if r.get('status') == 'executed')
        failed = sum(1 for r in repairs if r.get('status') == 'failed')
        rejected = sum(1 for r in repairs if r.get('status') == 'rejected')

        col1, col2, col3 = st.columns(3)
        col1.metric("成功执行", executed)
        col2.metric("执行失败", failed)
        col3.metric("已拒绝", rejected)

        st.markdown("---")

        for repair in repairs:
            render_repair_card(repair, api_base, config, show_approve=False)

    except Exception as e:
        st.error(f"加载失败: {str(e)}")


def render_repair_card(repair, api_base, config, show_approve=False):
    """Render a single repair request card"""

    request_id = repair.get('request_id', 'unknown')
    operation = repair.get('operation', 'unknown')
    reason = repair.get('reason', '')
    status = repair.get('status', 'unknown')
    created_at = repair.get('created_at', 'unknown')
    parameters = repair.get('parameters', {})

    # Status styling
    status_map = {
        'pending': ('⏸️', 'warning', '待审批'),
        'approved': ('✅', 'info', '已批准'),
        'executing': ('⚙️', 'info', '执行中'),
        'executed': ('✅', 'success', '已执行'),
        'failed': ('❌', 'error', '执行失败'),
        'rejected': ('🚫', 'error', '已拒绝'),
    }
    icon, color, label = status_map.get(status, ('•', 'info', status))

    with st.expander(f"{icon} {operation.upper()} - {label} - {created_at}"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(f"**请求 ID**: `{request_id}`")
            st.markdown(f"**操作类型**: {operation}")
            st.markdown(f"**状态**: {label}")

        with col2:
            st.markdown(f"**创建时间**: {created_at}")
            st.markdown(f"**原因**: {reason or '—'}")

        # Parameters
        if parameters:
            st.markdown("**操作参数**:")
            st.json(parameters)

        # Approval section
        if show_approve and status == 'pending':
            st.markdown("---")
            st.markdown("**审批操作**")

            col_approve, col_reject = st.columns(2)

            with col_approve:
                approval_token = st.text_input(
                    "审批令牌",
                    type="password",
                    key=f"token_approve_{request_id}",
                    help="需要配置的审批令牌才能执行操作"
                )

                if st.button("✅ 批准执行", use_container_width=True, type="primary", key=f"approve_{request_id}"):
                    if not approval_token:
                        st.error("请输入审批令牌")
                    else:
                        try:
                            resp = requests.post(
                                f"{api_base}/api/repairs/{request_id}/approve",
                                json={"approver": config.AIOPS_APPROVER_ID, "token": approval_token},
                                timeout=120
                            )
                            if resp.ok:
                                st.success("✅ 修复任务已批准并开始执行")
                                st.rerun()
                            else:
                                st.error(f"批准失败: {resp.text}")
                        except Exception as e:
                            st.error(f"请求失败: {str(e)}")

            with col_reject:
                reject_reason = st.text_input(
                    "拒绝原因",
                    key=f"reject_reason_{request_id}",
                    placeholder="说明拒绝的理由..."
                )

                if st.button("🚫 拒绝", use_container_width=True, key=f"reject_{request_id}"):
                    if not reject_reason:
                        st.error("请输入拒绝原因")
                    else:
                        try:
                            resp = requests.post(
                                f"{api_base}/api/repairs/{request_id}/reject",
                                json={"approver": config.AIOPS_APPROVER_ID, "reason": reject_reason, "token": approval_token},
                                timeout=10
                            )
                            if resp.ok:
                                st.success("🚫 请求已拒绝")
                                st.rerun()
                            else:
                                st.error(f"拒绝失败: {resp.text}")
                        except Exception as e:
                            st.error(f"请求失败: {str(e)}")

        # Execution result
        result = repair.get('result')
        if result:
            st.markdown("---")
            st.markdown("**执行结果**:")
            st.json(result)
