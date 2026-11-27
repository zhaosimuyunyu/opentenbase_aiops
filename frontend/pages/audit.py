"""AI Health Audit Page - AI 健康巡检"""
import streamlit as st
from api_client import requests
import json
from datetime import datetime

def render(db_connector, config, llm_client):
    """Render AI health audit page"""

    # Page Header
    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 诊断</div>
            <div class="page-title">AI 健康巡检</div>
            <div class="page-description">
                使用 AI 大模型分析集群健康状况，自动识别性能瓶颈、锁冲突、统计过期等问题并提供优化建议
            </div>
        </div>
    """, unsafe_allow_html=True)

    api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"

    # Audit Configuration
    st.markdown("""
        <div style="margin-bottom: 1.5rem;">
            <h3 style="font-size: 1.1rem; font-weight: 700; margin-bottom: 0.75rem;">巡检配置</h3>
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        target_tables = st.text_input(
            "目标表（可选）",
            placeholder="例如: public.orders, public.users",
            help="指定要巡检的表，逗号分隔。留空则全库巡检。",
            key="audit_target_tables"
        )

    with col2:
        audit_reason = st.text_input(
            "巡检原因",
            value="定期健康检查",
            help="记录本次巡检的目的",
            key="audit_reason"
        )

    # Run Audit Button
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 4])
    with col_btn1:
        run_audit = st.button("🚀 开始巡检", use_container_width=True, type="primary")
    with col_btn2:
        if st.button("📊 查看历史", use_container_width=True):
            st.session_state["navigation_page"] = "📜 巡检历史"
            st.rerun()

    if run_audit:
        st.markdown("---")
        st.markdown("### 🔍 巡检进行中...")

        progress_bar = st.progress(0, text="准备巡检...")
        status_placeholder = st.empty()

        try:
            # Step 1: Collect data
            progress_bar.progress(20, text="📊 采集集群数据...")
            status_placeholder.info("正在从 CN/DN 节点采集性能指标、锁信息、表统计等数据...")

            # Prepare request
            target = next((t.strip() for t in target_tables.split(",") if t.strip()), None)

            # Step 2: Call API
            progress_bar.progress(40, text="🤖 AI 分析中...")
            status_placeholder.info("DeepSeek 模型正在分析采集到的证据，生成诊断报告...")

            response = requests.post(
                f"{api_base}/api/audits/health",
                params={"table": target} if target else None,
                timeout=config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS if hasattr(config, 'AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS') else 210
            )

            progress_bar.progress(80, text="📝 生成报告...")

            if response.ok:
                audit_result = response.json()
                progress_bar.progress(100, text="✅ 巡检完成！")
                status_placeholder.empty()

                # Display results
                display_audit_results(audit_result, api_base, config)

            else:
                progress_bar.empty()
                status_placeholder.empty()
                st.error(f"巡检失败: {response.status_code} - {response.text}")

        except requests.Timeout:
            progress_bar.empty()
            status_placeholder.empty()
            st.error("巡检超时，请检查 API 服务状态或增加超时时间")
        except Exception as e:
            progress_bar.empty()
            status_placeholder.empty()
            st.error(f"巡检过程中发生错误: {str(e)}")

    # Show latest audit if no new audit running
    if not run_audit:
        st.markdown("---")
        st.markdown("### 📋 最近的巡检结果")

        try:
            response = requests.get(
                f"{api_base}/api/audits",
                params={"limit": 1, "audit_type": "readonly_health_audit"},
                timeout=10
            )

            if response.ok:
                audits = response.json().get("items", [])
                if audits:
                    latest_audit = audits[0]

                    # Get detailed audit
                    detail_response = requests.get(
                        f"{api_base}/api/audits/{latest_audit['audit_id']}",
                        timeout=10
                    )

                    if detail_response.ok:
                        audit_detail = detail_response.json()
                        display_audit_results(audit_detail, api_base, config)
                    else:
                        st.warning("无法加载巡检详情")
                else:
                    st.info("暂无巡检记录，点击「开始巡检」运行第一次健康检查")
            else:
                st.warning("无法连接到 API 服务")

        except Exception as e:
            st.error(f"加载巡检历史失败: {str(e)}")


def display_audit_results(audit_result, api_base, config):
    """Display audit results in a structured format"""

    audit_id = audit_result.get('audit_id', 'unknown')
    created_at = audit_result.get('created_at', 'unknown')
    risk_level = audit_result.get('risk_level', 'unknown')

    evidence = audit_result.get('evidence', {})
    findings = evidence.get('findings', [])
    collection_status = evidence.get('collection_status', 'unknown')
    analysis = audit_result.get('analysis', {})

    # Audit Header
    risk_colors = {
        'high': 'error',
        'medium': 'warning',
        'low': 'info',
        'none': 'success'
    }
    risk_color = risk_colors.get(risk_level, 'info')

    risk_labels = {
        'high': '高风险',
        'medium': '中等风险',
        'low': '低风险',
        'none': '无风险'
    }
    risk_label = risk_labels.get(risk_level, risk_level)

    st.markdown(f"""
        <div class="alert-banner {risk_color}">
            <div class="alert-icon">{'🚨' if risk_level == 'high' else '⚠️' if risk_level == 'medium' else '✅'}</div>
            <div class="alert-content">
                <div class="alert-title">巡检完成 - {risk_label}</div>
                <div class="alert-message">
                    巡检 ID: {audit_id} | 时间: {created_at} | 发现 {len(findings)} 个问题
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Collection Status
    if collection_status == 'partial':
        st.warning("⚠️ 数据采集部分完成，可能缺少部分节点或表的统计信息")
    elif collection_status == 'error':
        st.error("❌ 数据采集失败")

    # Key Metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("发现问题", len(findings))
    with col2:
        high_severity = sum(1 for f in findings if f.get('severity') == 'high')
        st.metric("高严重性", high_severity)
    with col3:
        st.metric("风险等级", risk_label)
    with col4:
        st.metric("数据完整性", "完整" if collection_status == 'success' else "部分")

    # Findings
    if findings:
        st.markdown("---")
        st.markdown("### 🔍 诊断发现")

        # Group by severity
        high_findings = [f for f in findings if f.get('severity') == 'high']
        medium_findings = [f for f in findings if f.get('severity') == 'medium']
        low_findings = [f for f in findings if f.get('severity') == 'low']

        for severity, finding_list, label, icon in [
            ('high', high_findings, '高优先级问题', '🚨'),
            ('medium', medium_findings, '中等优先级问题', '⚠️'),
            ('low', low_findings, '低优先级问题', 'ℹ️')
        ]:
            if finding_list:
                st.markdown(f"#### {icon} {label}")

                for idx, finding in enumerate(finding_list):
                    with st.expander(f"{finding.get('observed', '未知问题')}", expanded=(severity == 'high')):
                        st.markdown(f"**检查项**: `{finding.get('check', 'unknown')}`")
                        st.markdown(f"**严重程度**: {finding.get('severity', 'unknown')}")

                        if finding.get('impact'):
                            st.markdown(f"**影响**: {finding.get('impact')}")

                        if finding.get('recommendation'):
                            st.markdown(f"**建议**: {finding.get('recommendation')}")

                        if finding.get('evidence'):
                            st.json(finding.get('evidence'))
    else:
        st.markdown("""
            <div class="alert-banner success">
                <div class="alert-icon">✅</div>
                <div class="alert-content">
                    <div class="alert-title">集群健康状况良好</div>
                    <div class="alert-message">本次巡检未发现需要关注的问题</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    # AI Analysis
    if analysis:
        st.markdown("---")
        st.markdown("### 🤖 AI 诊断报告")

        structured = analysis.get('structured', {})

        if structured.get('summary'):
            st.markdown("#### 概要")
            st.write(structured.get('summary'))

        if structured.get('findings'):
            st.markdown("#### AI 分析发现")
            for ai_finding in structured['findings']:
                st.markdown(f"- **{ai_finding.get('title')}**: {ai_finding.get('description')}")

        if structured.get('recommendations'):
            st.markdown("#### 优化建议")
            for idx, rec in enumerate(structured['recommendations'], 1):
                st.markdown(f"{idx}. {rec}")

        # Show raw analysis if available
        with st.expander("查看完整 AI 分析"):
            st.json(analysis)

    # Actions
    st.markdown("---")
    st.markdown("### ⚡ 快速操作")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔄 重新分析", use_container_width=True, key=f"reanalyze_{audit_id}"):
            try:
                response = requests.post(
                    f"{api_base}/api/audits/{audit_id}/reanalyze",
                    timeout=config.AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS if hasattr(config, 'AIOPS_HEALTH_AUDIT_HTTP_TIMEOUT_SECONDS') else 210
                )
                if response.ok:
                    st.success("✅ 重新分析完成")
                    st.rerun()
                else:
                    st.error(f"重新分析失败: {response.text}")
            except Exception as e:
                st.error(f"请求失败: {str(e)}")

    with col2:
        if st.button("🧾 创建修复提案", use_container_width=True, key=f"repair_{audit_id}"):
            st.session_state["navigation_page"] = "🧾 修复中心"
            st.session_state["selected_audit_id"] = audit_id
            st.rerun()

    with col3:
        if st.button("📊 查看详细证据", use_container_width=True, key=f"evidence_{audit_id}"):
            with st.expander("原始证据数据", expanded=True):
                st.json(evidence)
