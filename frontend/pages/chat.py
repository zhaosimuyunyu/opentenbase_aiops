"""AI Chat Assistant Page - 智能助手"""
import streamlit as st
import requests
import json

def render(config):
    """Render AI chat assistant page"""

    st.markdown("""
        <div class="page-header">
            <div class="page-breadcrumb">OPENTENBASE AIOPS / 助手</div>
            <div class="page-title">智能助手</div>
            <div class="page-description">
                结合实时数据库工具与 OpenTenBase 知识库，诊断运维问题、提供优化建议、解答常见疑问
            </div>
        </div>
    """, unsafe_allow_html=True)

    api_base = config.AIOPS_API_URL if hasattr(config, 'AIOPS_API_URL') else "http://aiops-api:8000"

    # Initialize chat history in session state
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
        # Welcome message
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": """👋 你好！我是 OpenTenBase 智能运维助手。

我可以帮助你：
• 🔍 **实时诊断**：查询集群状态、锁情况、性能指标
• 💡 **问题解答**：回答 OpenTenBase 相关的技术问题
• 🛠️ **优化建议**：提供 SQL 优化和配置调优建议
• 📚 **知识查询**：检索官方文档和最佳实践

请问有什么可以帮助你的？"""
        })

    # Quick action buttons
    st.markdown("#### 💬 快速提问")
    quick_questions = [
        "当前集群状态如何？",
        "有没有锁等待的会话？",
        "如何优化慢查询？",
        "什么是分布式事务？",
    ]

    cols = st.columns(len(quick_questions))
    for idx, question in enumerate(quick_questions):
        with cols[idx]:
            if st.button(question, use_container_width=True, key=f"quick_q_{idx}"):
                st.session_state["pending_question"] = question

    # Display chat history
    st.markdown("---")

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

            # Show tool calls if available
            if message.get("tool_calls"):
                with st.expander("🔧 工具调用详情"):
                    for tool_call in message["tool_calls"]:
                        st.markdown(f"**工具**: `{tool_call.get('tool', 'unknown')}`")
                        if tool_call.get("result"):
                            st.code(json.dumps(tool_call["result"], ensure_ascii=False, indent=2), language="json")

    # Handle pending question from quick buttons
    if "pending_question" in st.session_state:
        user_input = st.session_state.pending_question
        del st.session_state.pending_question
        handle_user_input(user_input, api_base, config)

    # Chat input
    if prompt := st.chat_input("输入你的问题..."):
        handle_user_input(prompt, api_base, config)


def handle_user_input(user_input, api_base, config):
    """Handle user chat input"""

    # Add user message to history
    st.session_state.chat_messages.append({
        "role": "user",
        "content": user_input
    })

    # Display user message
    with st.chat_message("user"):
        st.markdown(user_input)

    # Get AI response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("🤔 思考中...")

        try:
            # Call chat API
            response = requests.post(
                f"{api_base}/api/qa/ask/stream",
                json={
                    "question": user_input,
                    "history": [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in st.session_state.chat_messages[:-1]  # Exclude the message we just added
                    ]
                },
                stream=True, timeout=900
            )

            if response.ok:
                result = None
                tool_calls = []
                for raw_line in response.iter_lines(chunk_size=1):
                    if not raw_line or not raw_line.startswith(b"data:"):
                        continue
                    event = json.loads(raw_line[5:])
                    if event.get("type") == "tool":
                        tool_calls.append(event)
                        message_placeholder.info(f"正在调用 {event.get('tool', '数据库工具')} · 第 {event.get('round', 0)} 轮")
                    elif event.get("type") == "result":
                        result = event
                        break
                    elif event.get("type") == "error":
                        raise RuntimeError(event.get("message", "Agent 请求失败"))
                if result is None:
                    raise RuntimeError("Agent 流在返回结果前中断")
                assistant_message = result.get("answer", "抱歉，我无法生成回答。")
                tool_calls = result.get("tool_trace", tool_calls)

                # Display response
                message_placeholder.markdown(assistant_message)

                # Show tool calls if any
                if tool_calls:
                    with st.expander("🔧 工具调用详情"):
                        for tool_call in tool_calls:
                            st.markdown(f"**工具**: `{tool_call.get('tool', 'unknown')}`")
                            st.markdown(f"**参数**: {tool_call.get('parameters', {})}")
                            if tool_call.get("result"):
                                st.code(json.dumps(tool_call["result"], ensure_ascii=False, indent=2)[:500], language="json")

                # Add to history
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": assistant_message,
                    "tool_calls": tool_calls
                })

            else:
                error_msg = f"❌ 请求失败: {response.status_code}\n\n{response.text}"
                message_placeholder.markdown(error_msg)
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": error_msg
                })

        except requests.ConnectionError:
            error_msg = "❌ 无法连接到 API 服务，请确认服务正在运行"
            message_placeholder.markdown(error_msg)
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": error_msg
            })
        except requests.Timeout:
            error_msg = "⏱️ 请求超时，请稍后重试"
            message_placeholder.markdown(error_msg)
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": error_msg
            })
        except Exception as e:
            error_msg = f"❌ 发生错误: {str(e)}"
            message_placeholder.markdown(error_msg)
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": error_msg
            })

    st.rerun()


# Sidebar controls
with st.sidebar:
    st.markdown("---")
    st.markdown("#### 💬 会话控制")

    if st.button("🗑️ 清空对话历史", use_container_width=True):
        st.session_state.chat_messages = []
        st.rerun()

    if st.session_state.get("chat_messages"):
        message_count = len([m for m in st.session_state.chat_messages if m["role"] == "user"])
        st.caption(f"已发送 {message_count} 条消息")
