"""SQL Audit Page - SQL 审核"""
import streamlit as st
import requests

SAMPLE_QUERIES = [
    ("全表扫描示例", "SELECT * FROM orders WHERE status = 'pending';"),
    ("大事务示例", "BEGIN; DELETE FROM logs WHERE created_at < '2024-01-01'; UPDATE stats SET total = 0;"),
    ("缺少索引条件", "SELECT * FROM users;"),
    ("安全查询示例", "SELECT id, name FROM users WHERE id = 1;"),
    ("带条件更新", "UPDATE orders SET status = 'done' WHERE id = 42;"),
]

def render(config):
    """Render SQL audit page"""

    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 质量</div>
            <div class="page-title">SQL 审核</div>
            <div class="page-description">
                上线前自动扫描 SQL 风险，拦截全表扫描、大事务、高风险 DDL 等操作，提供只读 EXPLAIN 分析
            </div>
        </div>
    """, unsafe_allow_html=True)

    api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("#### 输入 SQL 语句")

        # Quick template buttons
        st.markdown("**快速示例**")
        sample_cols = st.columns(len(SAMPLE_QUERIES))
        for idx, (label, _) in enumerate(SAMPLE_QUERIES):
            with sample_cols[idx]:
                if st.button(label, use_container_width=True, key=f"sample_{idx}"):
                    st.session_state["sql_audit_input"] = SAMPLE_QUERIES[idx][1]

        sql_input = st.text_area(
            "SQL",
            height=220,
            placeholder="在这里输入要审核的 SQL 语句...\n\n例如：SELECT * FROM orders WHERE status = 'pending';",
            key="sql_audit_input",
            label_visibility="collapsed"
        )

        col_btn1, col_btn2 = st.columns([1, 3])
        with col_btn1:
            run_audit = st.button("🔍 开始审核", type="primary", use_container_width=True)
        with col_btn2:
            if st.button("🧹 清空", use_container_width=True):
                st.session_state["sql_audit_input"] = ""
                st.rerun()

    with col_right:
        st.markdown("#### 审核规则说明")
        st.markdown("""
            <div class="card" style="font-size:0.85rem; line-height:1.7;">
                <div style="margin-bottom:.75rem; font-weight:700; color:var(--error);">🚨 高风险规则</div>
                <div>• 全表扫描（无 WHERE 条件）</div>
                <div>• DROP TABLE / DROP DATABASE</div>
                <div>• TRUNCATE 表操作</div>
                <div style="margin-top:.75rem; margin-bottom:.75rem; font-weight:700; color:var(--warning);">⚠️ 中等风险规则</div>
                <div>• UPDATE / DELETE 无 WHERE</div>
                <div>• 大事务（多语句）</div>
                <div>• 修改核心系统表</div>
                <div style="margin-top:.75rem; margin-bottom:.75rem; font-weight:700; color:var(--info);">ℹ️ 低风险规则</div>
                <div>• SELECT *（建议指定列名）</div>
                <div>• 缺少 LIMIT 子句</div>
                <div>• 不推荐的函数使用</div>
            </div>
        """, unsafe_allow_html=True)

    # Run audit
    if run_audit:
        if not sql_input or not sql_input.strip():
            st.warning("请先输入要审核的 SQL 语句")
        else:
            st.markdown("---")
            with st.spinner("正在分析 SQL..."):
                try:
                    response = requests.post(
                        f"{api_base}/api/sql-audit",
                        json={"sql": sql_input.strip()},
                        timeout=30
                    )

                    if response.ok:
                        result = response.json()
                        display_audit_result(result, sql_input)
                    else:
                        st.error(f"审核请求失败: {response.status_code}")
                        st.code(response.text)

                except requests.ConnectionError:
                    st.error("无法连接到 API 服务，请确认服务正在运行")
                except requests.Timeout:
                    st.error("审核超时，请稍后重试")
                except Exception as e:
                    st.error(f"审核发生错误: {str(e)}")


def display_audit_result(result, original_sql):
    """Display SQL audit results"""

    risk_level = result.get('risk_level', 'unknown')
    rules_hit = result.get('rules', [])
    explain_result = result.get('explain')
    explain_error = result.get('explain_error')

    # Risk level banner
    risk_map = {
        'high':   ('error',   '🚨', '高风险 — 建议拦截此 SQL'),
        'medium': ('warning', '⚠️', '中等风险 — 请仔细确认后执行'),
        'low':    ('info',    'ℹ️', '低风险 — 注意优化建议'),
        'none':   ('success', '✅', '通过审核 — 未命中风险规则'),
    }
    color, icon, msg = risk_map.get(risk_level, ('info', 'ℹ️', '未知风险等级'))

    st.markdown(f"""
        <div class="alert-banner {color}">
            <div class="alert-icon">{icon}</div>
            <div class="alert-content">
                <div class="alert-title">{msg}</div>
                <div class="alert-message">命中规则数: {len(rules_hit)}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        # Rules hit
        st.markdown("#### 命中规则")
        if rules_hit:
            for rule in rules_hit:
                sev = rule.get('severity', 'low')
                sev_colors = {'high': 'var(--error)', 'medium': 'var(--warning)', 'low': 'var(--info)'}
                sev_color = sev_colors.get(sev, 'var(--text-secondary)')
                sev_labels = {'high': '高风险', 'medium': '中等风险', 'low': '低风险'}
                sev_label = sev_labels.get(sev, sev)

                st.markdown(f"""
                    <div style="
                        background: var(--bg-secondary);
                        border: 1px solid var(--border-primary);
                        border-left: 4px solid {sev_color};
                        border-radius: 8px;
                        padding: 0.9rem 1rem;
                        margin-bottom: 0.75rem;
                    ">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:.4rem;">
                            <strong style="font-size:.9rem;">{rule.get('name', '未知规则')}</strong>
                            <span style="font-size:.7rem; font-weight:700; color:{sev_color};">{sev_label}</span>
                        </div>
                        <div style="color:var(--text-secondary); font-size:.82rem; line-height:1.5;">
                            {rule.get('description', '')}
                        </div>
                        {f'<div style="margin-top:.4rem; color:var(--text-tertiary); font-size:.78rem;">建议: {rule.get("suggestion","")}</div>' if rule.get("suggestion") else ''}
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
                <div class="alert-banner success">
                    <div class="alert-icon">✅</div>
                    <div class="alert-content">
                        <div class="alert-message">未命中任何风险规则</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    with col2:
        # EXPLAIN plan
        st.markdown("#### 执行计划 (EXPLAIN)")
        if explain_result:
            st.code(json_or_text(explain_result), language="json")
        elif explain_error:
            st.warning(f"无法获取执行计划: {explain_error}")
        else:
            st.info("该 SQL 类型不支持只读 EXPLAIN（仅支持 SELECT / WITH / VALUES）")

        # Original SQL
        st.markdown("#### 原始 SQL")
        st.code(original_sql, language="sql")


def json_or_text(value):
    """Try to pretty-print if value is JSON, else return as-is"""
    import json
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except Exception:
        return str(value)
