"""OpenTenBase AIOps - Modern Redesigned UI"""
import streamlit as st
import sys
import os
import requests
import json
import html
from pathlib import Path
from datetime import datetime
import pandas as pd

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
    page_title="OpenTenBase AIOps Platform",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Modern Professional Theme - Inspired by Linear, Vercel, and Tailwind
st.markdown("""
<style>
    /* ========== Color System ========== */
    :root {
        --bg-primary: #fafafa;
        --bg-secondary: #ffffff;
        --bg-tertiary: #f5f5f5;
        --bg-elevated: #ffffff;

        --text-primary: #171717;
        --text-secondary: #737373;
        --text-tertiary: #a3a3a3;

        --border-primary: #e5e5e5;
        --border-secondary: #f5f5f5;

        --accent-primary: #0ea5e9;
        --accent-hover: #0284c7;
        --accent-light: #e0f2fe;

        --success: #10b981;
        --success-light: #d1fae5;
        --warning: #f59e0b;
        --warning-light: #fef3c7;
        --error: #ef4444;
        --error-light: #fee2e2;
        --info: #6366f1;
        --info-light: #e0e7ff;

        --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05);
        --shadow-md: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        --shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1);
        --shadow-xl: 0 20px 25px -5px rgb(0 0 0 / 0.1);
    }

    /* Dark mode adjustments */
    @media (prefers-color-scheme: dark) {
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #171717;
            --bg-tertiary: #262626;
            --bg-elevated: #1f1f1f;

            --text-primary: #fafafa;
            --text-secondary: #a3a3a3;
            --text-tertiary: #737373;

            --border-primary: #262626;
            --border-secondary: #171717;
        }
    }

    /* ========== Layout & Base ========== */
    html, body, [data-testid="stAppViewContainer"] {
        background: var(--bg-primary);
        color: var(--text-primary);
        font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Helvetica, Arial, sans-serif;
    }

    [data-testid="stHeader"] {
        background: rgba(250, 250, 250, 0.8);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid var(--border-primary);
    }

    .main .block-container {
        max-width: 1400px;
        padding: 2rem 3rem 4rem;
    }

    /* ========== Sidebar ========== */
    [data-testid="stSidebar"] {
        background: var(--bg-secondary);
        border-right: 1px solid var(--border-primary);
    }

    [data-testid="stSidebar"] > div:first-child {
        padding: 1.5rem 1rem;
    }

    /* Brand Lockup */
    .brand-container {
        padding: 0 0.5rem 1.5rem;
        margin-bottom: 1rem;
        border-bottom: 1px solid var(--border-primary);
    }

    .brand-logo {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        margin-bottom: 0.5rem;
    }

    .brand-icon {
        width: 32px;
        height: 32px;
        background: linear-gradient(135deg, var(--accent-primary), var(--info));
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
    }

    .brand-name {
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--text-primary);
        letter-spacing: -0.02em;
    }

    .brand-subtitle {
        font-size: 0.75rem;
        color: var(--text-secondary);
        padding-left: 0.25rem;
    }

    /* Navigation */
    .nav-section {
        margin-bottom: 1.5rem;
    }

    .nav-label {
        font-size: 0.65rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-tertiary);
        padding: 0 0.75rem;
        margin-bottom: 0.5rem;
    }

    [data-testid="stSidebar"] [data-testid="stRadio"] > label {
        display: none;
    }

    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 2px;
    }

    [data-testid="stSidebar"] [role="radiogroup"] label {
        padding: 0.5rem 0.75rem;
        border-radius: 6px;
        transition: all 0.15s ease;
        cursor: pointer;
        font-size: 0.875rem;
        color: var(--text-secondary);
        font-weight: 500;
    }

    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background: var(--bg-tertiary);
        color: var(--text-primary);
    }

    [data-testid="stSidebar"] [role="radiogroup"] [data-baseweb="radio"] input:checked + div + div label {
        background: var(--accent-light);
        color: var(--accent-primary);
        font-weight: 600;
    }

    /* Connection Status */
    .connection-info {
        margin-top: 1.5rem;
        padding: 1rem;
        background: var(--bg-tertiary);
        border-radius: 8px;
        border: 1px solid var(--border-primary);
    }

    .connection-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 0.75rem;
        color: var(--text-secondary);
        padding: 0.25rem 0;
    }

    .connection-label {
        color: var(--text-tertiary);
    }

    .connection-value {
        font-family: ui-monospace, monospace;
        color: var(--text-primary);
    }

    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: 600;
    }

    .status-badge.online {
        background: var(--success-light);
        color: var(--success);
    }

    .status-badge.offline {
        background: var(--error-light);
        color: var(--error);
    }

    .status-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: currentColor;
    }

    /* ========== Main Content ========== */

    /* Page Header */
    .page-header {
        margin-bottom: 2rem;
        padding-bottom: 1.5rem;
        border-bottom: 1px solid var(--border-primary);
    }

    .page-breadcrumb {
        font-size: 0.75rem;
        color: var(--text-tertiary);
        margin-bottom: 0.5rem;
        font-weight: 500;
    }

    .page-title {
        font-size: 2rem;
        font-weight: 800;
        color: var(--text-primary);
        letter-spacing: -0.03em;
        margin-bottom: 0.5rem;
    }

    .page-description {
        font-size: 0.95rem;
        color: var(--text-secondary);
        line-height: 1.6;
    }

    /* Cards */
    .card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-primary);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: var(--shadow-sm);
        transition: all 0.2s ease;
    }

    .card:hover {
        box-shadow: var(--shadow-md);
        border-color: var(--border-secondary);
    }

    .card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }

    .card-title {
        font-size: 1rem;
        font-weight: 700;
        color: var(--text-primary);
    }

    .card-action {
        font-size: 0.8rem;
        color: var(--text-tertiary);
    }

    /* Metrics Grid */
    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin-bottom: 2rem;
    }

    .metric-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-primary);
        border-radius: 10px;
        padding: 1.25rem;
        transition: all 0.2s ease;
    }

    .metric-card:hover {
        border-color: var(--accent-primary);
        box-shadow: var(--shadow-md);
    }

    .metric-label {
        font-size: 0.75rem;
        color: var(--text-tertiary);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.5rem;
    }

    .metric-value {
        font-size: 1.75rem;
        font-weight: 800;
        color: var(--text-primary);
        line-height: 1;
        margin-bottom: 0.5rem;
    }

    .metric-change {
        font-size: 0.75rem;
        font-weight: 600;
    }

    .metric-change.positive {
        color: var(--success);
    }

    .metric-change.negative {
        color: var(--error);
    }

    .metric-change.neutral {
        color: var(--text-tertiary);
    }

    /* Alert Banners */
    .alert-banner {
        display: flex;
        align-items: flex-start;
        gap: 1rem;
        padding: 1rem 1.25rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        border: 1px solid;
    }

    .alert-banner.success {
        background: var(--success-light);
        border-color: var(--success);
        color: var(--success);
    }

    .alert-banner.warning {
        background: var(--warning-light);
        border-color: var(--warning);
        color: var(--warning);
    }

    .alert-banner.error {
        background: var(--error-light);
        border-color: var(--error);
        color: var(--error);
    }

    .alert-banner.info {
        background: var(--info-light);
        border-color: var(--info);
        color: var(--info);
    }

    .alert-icon {
        font-size: 1.25rem;
        flex-shrink: 0;
    }

    .alert-content {
        flex: 1;
    }

    .alert-title {
        font-weight: 700;
        font-size: 0.9rem;
        margin-bottom: 0.25rem;
        color: var(--text-primary);
    }

    .alert-message {
        font-size: 0.85rem;
        color: var(--text-secondary);
        line-height: 1.5;
    }

    /* Node Cards */
    .node-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
        gap: 1rem;
        margin: 1.5rem 0;
    }

    .node-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-primary);
        border-radius: 10px;
        padding: 1.25rem;
        transition: all 0.2s ease;
        position: relative;
        overflow: hidden;
    }

    .node-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, var(--accent-primary), var(--info));
        opacity: 0;
        transition: opacity 0.2s ease;
    }

    .node-card:hover {
        border-color: var(--accent-primary);
        box-shadow: var(--shadow-md);
    }

    .node-card:hover::before {
        opacity: 1;
    }

    .node-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 0.75rem;
    }

    .node-name {
        font-size: 0.95rem;
        font-weight: 700;
        color: var(--text-primary);
    }

    .node-type {
        font-size: 0.7rem;
        padding: 0.2rem 0.5rem;
        border-radius: 4px;
        background: var(--bg-tertiary);
        color: var(--text-secondary);
        font-weight: 600;
    }

    .node-info {
        font-size: 0.75rem;
        color: var(--text-secondary);
        line-height: 1.6;
        font-family: ui-monospace, monospace;
    }

    /* Tables */
    [data-testid="stDataFrame"] {
        border: 1px solid var(--border-primary);
        border-radius: 10px;
        overflow: hidden;
    }

    /* Buttons */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
        font-size: 0.875rem;
        padding: 0.5rem 1.25rem;
        transition: all 0.15s ease;
        border: 1px solid var(--border-primary);
    }

    div.stButton > button[kind="primary"] {
        background: var(--accent-primary);
        border-color: var(--accent-primary);
        color: white;
    }

    div.stButton > button[kind="primary"]:hover {
        background: var(--accent-hover);
        border-color: var(--accent-hover);
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }

    div.stButton > button:hover {
        border-color: var(--accent-primary);
        color: var(--accent-primary);
    }

    /* Inputs */
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        border-radius: 8px;
        border: 1px solid var(--border-primary);
        font-size: 0.875rem;
    }

    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--accent-primary);
        box-shadow: 0 0 0 3px var(--accent-light);
    }

    /* Chat Messages */
    .stChatMessage {
        background: var(--bg-secondary);
        border: 1px solid var(--border-primary);
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
    }

    /* Progress Bar */
    .stProgress > div > div > div {
        background: var(--accent-primary);
        border-radius: 4px;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
        border-bottom: 1px solid var(--border-primary);
    }

    .stTabs [data-baseweb="tab"] {
        border-radius: 6px 6px 0 0;
        font-weight: 600;
        font-size: 0.875rem;
        color: var(--text-secondary);
    }

    .stTabs [aria-selected="true"] {
        background: var(--accent-light);
        color: var(--accent-primary);
    }

    /* Expander */
    [data-testid="stExpander"] {
        border: 1px solid var(--border-primary);
        border-radius: 10px;
        background: var(--bg-secondary);
    }

    /* Code Blocks */
    code {
        background: var(--bg-tertiary);
        padding: 0.2rem 0.4rem;
        border-radius: 4px;
        font-size: 0.85em;
        color: var(--accent-primary);
    }

    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
        height: 8px;
    }

    ::-webkit-scrollbar-track {
        background: var(--bg-primary);
    }

    ::-webkit-scrollbar-thumb {
        background: var(--border-primary);
        border-radius: 4px;
    }

    ::-webkit-scrollbar-thumb:hover {
        background: var(--text-tertiary);
    }

    /* Responsive */
    @media (max-width: 900px) {
        .main .block-container {
            padding: 1rem 1.5rem 2rem;
        }

        .page-title {
            font-size: 1.5rem;
        }

        .metrics-grid {
            grid-template-columns: 1fr;
        }

        .node-grid {
            grid-template-columns: 1fr;
        }
    }

    /* Loading Spinner */
    .stSpinner > div {
        border-color: var(--accent-primary);
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
    st.markdown("""
        <div class="brand-container">
            <div class="brand-logo">
                <div class="brand-icon">🤖</div>
                <div class="brand-name">OpenTenBase</div>
            </div>
            <div class="brand-subtitle">AI 智能运维平台</div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="nav-label">监控与诊断</div>', unsafe_allow_html=True)

    navigation = {
        "📊 集群总览": "overview",
        "🛡️ AI 健康巡检": "audit",
        "📜 巡检历史": "history",
        "🔍 性能诊断": "performance",
        "🧪 SQL 审核": "sql_audit",
        "💬 智能助手": "chat",
        "🧾 修复中心": "repairs",
    }

    selected = st.radio(
        "导航",
        list(navigation.keys()),
        label_visibility="collapsed"
    )

    page = navigation[selected]

    # Connection Test
    st.markdown('<div class="nav-label" style="margin-top: 1rem;">数据库连接</div>', unsafe_allow_html=True)

    if st.button("🔌 测试连接", use_container_width=True):
        with st.spinner("连接中..."):
            status = st.session_state.db_connector.test_connection()

            if status['connected']:
                st.success("✅ 连接成功", icon="✅")
            else:
                st.error(f"❌ 连接失败: {status.get('error', 'unknown')}", icon="❌")

    # Connection Info
    st.markdown(f"""
        <div class="connection-info">
            <div class="connection-row">
                <span class="connection-label">主机</span>
                <span class="connection-value">{st.session_state.config.DB_HOST}:{st.session_state.config.DB_PORT}</span>
            </div>
            <div class="connection-row">
                <span class="connection-label">数据库</span>
                <span class="connection-value">{st.session_state.config.DB_NAME}</span>
            </div>
            <div class="connection-row">
                <span class="connection-label">用户</span>
                <span class="connection-value">{st.session_state.config.DB_USER}</span>
            </div>
            <div class="connection-row" style="margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid var(--border-primary);">
                <span class="connection-label">AI 模型</span>
                <span class="connection-value">{st.session_state.config.DEEPSEEK_MODEL}</span>
            </div>
        </div>
    """, unsafe_allow_html=True)

# Page content routing
if page == "overview":
    from frontend.pages import overview
    overview.render(st.session_state.db_connector, st.session_state.config)

elif page == "audit":
    from frontend.pages import audit
    audit.render(st.session_state.db_connector, st.session_state.config, st.session_state.llm_client)

elif page == "history":
    from frontend.pages import history
    history.render(st.session_state.config)

elif page == "performance":
    from frontend.pages import performance
    performance.render(st.session_state.db_connector, st.session_state.config)

elif page == "sql_audit":
    from frontend.pages import sql_audit
    sql_audit.render(st.session_state.config)

elif page == "chat":
    from frontend.pages import chat
    chat.render(st.session_state.config)

elif page == "repairs":
    from frontend.pages import repairs
    repairs.render(st.session_state.config)
