"""AI Chat Assistant Page - 智能助手"""
import streamlit as st
import requests
import json
import uuid


def save_session(api_base, session_id, session):
    try:
        response = requests.put(
            f"{api_base}/api/agent/sessions/{session_id}",
            json={"session_id": session_id, **session},
            timeout=15,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False


def load_sessions(api_base):
    sessions = st.session_state.agent_sessions
    try:
        response = requests.get(f"{api_base}/api/agent/sessions", timeout=15)
        response.raise_for_status()
        for item in response.json().get("items", []):
            sessions[item["session_id"]] = {
                "title": item.get("title") or "新会话",
                "messages": item.get("messages") or [],
            }
    except requests.RequestException:
        pass

    legacy_messages = st.session_state.pop("chat_messages", [])
    if not sessions:
        session_id = str(uuid.uuid4())
        sessions[session_id] = {"title": "新会话", "messages": legacy_messages}
        save_session(api_base, session_id, sessions[session_id])
    if st.session_state.active_agent_session not in sessions:
        st.session_state.active_agent_session = next(iter(sessions))


def receive_turn(api_base, turn_id, message_placeholder):
    with requests.get(
        f"{api_base}/api/agent/turns/{turn_id}/stream",
        stream=True,
        timeout=900,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(chunk_size=1):
            if not raw_line or not raw_line.startswith(b"data:"):
                continue
            event = json.loads(raw_line[5:])
            if event.get("type") == "progress":
                message_placeholder.info(event.get("message", "后台任务仍在运行"))
            elif event.get("type") == "result":
                return event
            elif event.get("type") == "error":
                raise RuntimeError(event.get("message", "后台 Agent 任务未完成"))
    return None


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

    st.session_state.setdefault("agent_sessions", {})
    st.session_state.setdefault("active_agent_session", None)
    load_sessions(api_base)
    sessions = st.session_state.agent_sessions
    with st.sidebar:
        st.markdown("#### Agent 会话")
        session_ids = list(sessions)
        selected = st.selectbox(
            "会话", session_ids,
            index=session_ids.index(st.session_state.active_agent_session),
            format_func=lambda session_id: sessions[session_id]["title"],
            label_visibility="collapsed",
        )
        if selected != st.session_state.active_agent_session:
            st.session_state.active_agent_session = selected
            st.rerun()
        new_column, delete_column = st.columns(2)
        with new_column:
            if st.button("新建会话", use_container_width=True):
                session_id = str(uuid.uuid4())
                sessions[session_id] = {"title": "新会话", "messages": []}
                st.session_state.active_agent_session = session_id
                if not save_session(api_base, session_id, sessions[session_id]):
                    st.warning("会话已在本地创建，暂未保存到服务端。")
                st.rerun()
        with delete_column:
            can_delete = len(sessions) > 1
            if st.button("删除会话", use_container_width=True, disabled=not can_delete):
                session_id = st.session_state.active_agent_session
                try:
                    response = requests.delete(
                        f"{api_base}/api/agent/sessions/{session_id}", timeout=15
                    )
                    response.raise_for_status()
                    del sessions[session_id]
                    st.session_state.active_agent_session = next(iter(sessions))
                    st.rerun()
                except requests.RequestException as error:
                    st.error(f"删除会话失败：{error}")
    active_session = sessions[st.session_state.active_agent_session]
    try:
        response = requests.get(
            f"{api_base}/api/agent/turns",
            params={"session_id": st.session_state.active_agent_session, "limit": 1},
            timeout=15,
        )
        response.raise_for_status()
        latest_turns = response.json().get("items", [])
    except requests.RequestException:
        latest_turns = []
    if latest_turns and latest_turns[0]["status"] == "running":
        pending_turn = latest_turns[0]
        st.info("上一条回复仍在后台生成。")
        if st.button("恢复接收后台回复", key=f"resume-{pending_turn['turn_id']}"):
            with st.chat_message("assistant"):
                placeholder = st.empty()
                try:
                    receive_turn(api_base, pending_turn["turn_id"], placeholder)
                except Exception as error:
                    st.error(f"恢复回复失败：{error}")
            st.rerun()
    elif latest_turns and latest_turns[0]["status"] == "interrupted":
        st.warning("服务重启时中断了上一条任务，原问题仍保存在会话中，可重新提交。")
    elif latest_turns and latest_turns[0]["status"] == "failed":
        st.warning("上一条 Agent 任务执行失败，原问题仍保存在会话中，可重新提交。")

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

    for message in active_session["messages"]:
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
        handle_user_input(user_input, api_base, active_session, config)

    # Chat input
    if prompt := st.chat_input("输入你的问题..."):
        handle_user_input(prompt, api_base, active_session, config)


def handle_user_input(user_input, api_base, active_session, config):
    """Handle user chat input"""

    turn_id = str(uuid.uuid4())
    # Add user message to history
    active_session["messages"].append({
        "role": "user",
        "content": user_input,
        "turn_id": turn_id,
    })
    if active_session["title"] == "新会话":
        active_session["title"] = user_input[:24] + ("…" if len(user_input) > 24 else "")
    session_id = st.session_state.active_agent_session
    if not save_session(api_base, session_id, active_session):
        st.warning("问题已加入本地会话，但服务端暂时无法保存。")

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
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "history": [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in active_session["messages"][:-1]
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
                    if event.get("type") == "progress":
                        message_placeholder.info(event.get("message", "Agent 正在处理"))
                    elif event.get("type") == "tool":
                        tool_calls.append(event)
                        tool_name = event.get("tool", "数据库工具")
                        round_number = event.get("round", 0)
                        if event.get("stage") == "running":
                            message_placeholder.info(f"正在调用 {tool_name} · 第 {round_number} 轮")
                        elif event.get("stage") == "failed":
                            message_placeholder.warning(f"{tool_name} 调用失败 · 第 {round_number} 轮")
                        else:
                            message_placeholder.success(f"{tool_name} 已完成 · 第 {round_number} 轮")
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
                active_session["messages"].append({
                    "role": "assistant",
                    "content": assistant_message,
                    "tool_calls": tool_calls,
                    "turn_id": turn_id,
                })

            else:
                raise RuntimeError(f"请求失败：{response.status_code} {response.text}")
        except Exception as e:
            try:
                turn = requests.get(
                    f"{api_base}/api/agent/turns/{turn_id}", timeout=10
                ).json()
            except requests.RequestException:
                turn = None
            if turn and turn.get("status") == "completed":
                message_placeholder.markdown(turn.get("answer", ""))
            elif turn and turn.get("status") == "running":
                message_placeholder.info("连接已断开，Agent 仍在后台处理。稍后可恢复接收回复。")
            elif turn and turn.get("status") == "interrupted":
                message_placeholder.warning("Agent 服务重启时中断了任务，问题已保存在会话中。")
            else:
                message_placeholder.error(f"发生错误：{e}")

    st.rerun()
