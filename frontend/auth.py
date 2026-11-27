"""Shared-password gate for the server-rendered Streamlit interface."""
import hmac
import os


def ui_password_configured():
    return bool(os.getenv("AIOPS_UI_PASSWORD", ""))


def ui_password_matches(candidate, expected=None):
    expected = os.getenv("AIOPS_UI_PASSWORD", "") if expected is None else expected
    return bool(expected) and hmac.compare_digest(str(candidate), expected)


def require_ui_auth(st):
    expected = os.getenv("AIOPS_UI_PASSWORD", "")
    if not expected:
        return
    if st.session_state.get("_aiops_ui_authenticated") is True:
        return

    st.title("OpenTenBase AIOps")
    st.caption("请验证访问密码以继续")
    with st.form("aiops_ui_login", clear_on_submit=True):
        candidate = st.text_input("访问密码", type="password")
        submitted = st.form_submit_button("登录")

    if submitted:
        if ui_password_matches(candidate, expected):
            st.session_state["_aiops_ui_authenticated"] = True
            st.rerun()
        st.error("访问密码不正确")
    st.stop()
