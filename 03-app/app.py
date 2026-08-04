"""
DiningConcierge — Streamlit 프로덕션 앱
- 채팅 UI (st.chat_input + st.chat_message)
- 도구 호출 로그 (사이드바)
- 식당 상세 카드 (검색 결과)
- 사이드바: Memory 현황 + 취향 요약 + Runtime 상태 + 세션 관리
- Memory 연동: 세션 간 취향 유지 검증
"""

import uuid
import os
import re
import json
import streamlit as st
import boto3
from dotenv import load_dotenv

# .env 파일 로드 (없으면 환경변수에서 읽음)
load_dotenv()

# ── 설정 ──────────────────────────────────────────────
RUNTIME_ARN = os.environ.get("RUNTIME_ARN", "")
MEMORY_ID = os.environ.get("MEMORY_ID", "")
REGION = os.environ.get("AWS_REGION", "us-west-2")
GATEWAY_WEB_SEARCH_URL = os.environ.get("GATEWAY_WEB_SEARCH_URL", "")

# ── 도구 아이콘 매핑 ──────────────────────────────────
TOOL_ICONS = {
    "search_restaurants": "🔍",
    "get_menu": "📋",
    "check_reservation": "📅",
    "create_reservation": "✅",
    "estimate_cost": "💰",
    "web-search___WebSearch": "🌐",
    "WebSearch": "🌐",
}


# ── Web Search (Gateway 직접 호출) ────────────────────
def web_search(query: str, max_results: int = 5) -> str | None:
    """us-east-1 Gateway의 Web Search를 앱에서 직접 호출"""
    try:
        from strands.tools.mcp import MCPClient
        from mcp.client.streamable_http import streamablehttp_client

        mcp = MCPClient(lambda: streamablehttp_client(url=GATEWAY_WEB_SEARCH_URL))
        mcp.start()
        result = mcp.call_tool_sync(
            tool_use_id="app-websearch",
            name="web-search___WebSearch",
            arguments={"query": query, "maxResults": max_results}
        )
        mcp.stop(None, None, None)

        if result.get("status") == "success":
            content = result.get("content", [])
            if content:
                return content[0].get("text", "")
    except Exception:
        pass
    return None


# ── Memory 조회 함수 ──────────────────────────────────
def get_memory_status(actor_id: str) -> dict:
    """Memory 현황 종합 조회: 원본 대화 + 인덱싱된 long-term memory"""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    result = {
        "conversations": [],       # 원본 대화 (short-term)
        "indexed_preferences": [],  # 추출된 취향 (long-term)
        "indexed_facts": [],        # 추출된 사실 (long-term)
        "error": None,
    }

    # 1. 원본 대화 조회 (list_sessions → list_events)
    try:
        sessions_resp = client.list_sessions(memoryId=MEMORY_ID, actorId=actor_id)
        for s in sessions_resp.get("sessionSummaries", []):
            sid = s["sessionId"]
            try:
                events_resp = client.list_events(
                    memoryId=MEMORY_ID, actorId=actor_id, sessionId=sid
                )
                for event in events_resp.get("events", []):
                    for payload_item in event.get("payload", []):
                        conv = payload_item.get("conversational", {})
                        if conv:
                            result["conversations"].append({
                                "role": conv.get("role", "?"),
                                "text": conv.get("content", {}).get("text", ""),
                                "session_id": sid[:8],
                                "timestamp": str(event.get("eventTimestamp", ""))[:19],
                            })
            except Exception:
                pass
    except Exception:
        pass

    # 2. 인덱싱된 long-term memory 조회 (retrieve_memory_records)
    for ns_type in ["preferences", "facts"]:
        ns = f"/users/{actor_id}/{ns_type}"
        try:
            resp = client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespacePath=f"/users/{actor_id}/",
                searchCriteria={"searchQuery": "취향 선호 사실 정보", "topK": 20}
            )
            for r in resp.get("memoryRecordSummaries", []):
                record_ns = r.get("namespaces", [])
                if ns_type in str(record_ns):
                    result[f"indexed_{ns_type}"].append(r)
        except Exception:
            pass
        # namespace 직접 지정도 시도
        try:
            resp = client.list_memory_records(memoryId=MEMORY_ID, namespace=ns)
            for r in resp.get("memoryRecordSummaries", []):
                if r not in result[f"indexed_{ns_type}"]:
                    result[f"indexed_{ns_type}"].append(r)
        except Exception:
            pass
        try:
            resp = client.list_memory_records(memoryId=MEMORY_ID, namespace=f"{ns}/")
            for r in resp.get("memoryRecordSummaries", []):
                if r not in result[f"indexed_{ns_type}"]:
                    result[f"indexed_{ns_type}"].append(r)
        except Exception:
            pass

    return result


def search_memory(actor_id: str, query: str) -> list:
    """Memory에서 시맨틱 검색 (인덱싱 완료된 것만 반환)"""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    results = []

    for ns in [f"/users/{actor_id}/preferences", f"/users/{actor_id}/facts",
               f"/users/{actor_id}/preferences/", f"/users/{actor_id}/facts/"]:
        try:
            resp = client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespace=ns,
                searchCriteria={"searchQuery": query, "topK": 5}
            )
            for r in resp.get("memoryRecordSummaries", []):
                r["_namespace"] = ns.split("/")[-2] if ns.endswith("/") else ns.split("/")[-1]
                results.append(r)
        except Exception:
            pass

    return results


def save_conversation_to_memory(actor_id: str, user_text: str, assistant_text: str, session_id: str) -> str | None:
    """대화를 create_event로 Memory에 기록 → 자동 extraction으로 취향 추출
    유사한 내용이 이미 있으면 저장 스킵 (중복 방지)
    """
    from datetime import datetime, timezone
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    # 유사한 내용이 이미 있는지 확인 (score >= 0.60이면 중복으로 간주)
    try:
        for ns in [f"/users/{actor_id}/preferences", f"/users/{actor_id}/facts"]:
            resp = client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespace=ns,
                searchCriteria={"searchQuery": user_text, "topK": 3}
            )
            for r in resp.get("memoryRecordSummaries", []):
                if r.get("score", 0) >= 0.60:
                    print(f"[Memory] 중복 감지 (score={r['score']:.2f}), 저장 스킵")
                    return None
    except Exception:
        pass

    try:
        resp = client.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[
                {
                    "conversational": {
                        "content": {"text": user_text},
                        "role": "USER"
                    }
                },
                {
                    "conversational": {
                        "content": {"text": assistant_text},
                        "role": "ASSISTANT"
                    }
                }
            ]
        )
        event = resp.get("event", {})
        print(f"[Memory] ✅ create_event 성공: {event.get('eventId')}")
        return event.get("eventId")
    except Exception as e:
        print(f"[Memory] ❌ create_event 실패: {type(e).__name__}: {e}")
    return None


# ── 세션 저장/로드 ────────────────────────────────────
SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)


def get_session_file(session_id: str) -> str:
    return os.path.join(SESSION_DIR, f"{session_id}.json")


def save_session_to_file(session_id: str, messages: list, label: str = "") -> None:
    """세션 대화 내용을 파일로 저장"""
    data = {"session_id": session_id, "label": label, "messages": messages}
    with open(get_session_file(session_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_session_from_file(session_id: str) -> dict:
    """세션 파일 로드"""
    path = get_session_file(session_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"session_id": session_id, "label": "", "messages": []}


def list_saved_sessions() -> list[dict]:
    """저장된 세션 목록 반환 (최신순)"""
    sessions = []
    for fname in os.listdir(SESSION_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SESSION_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            msg_count = len([m for m in data.get("messages", []) if m.get("role") == "user"])
            sessions.append({
                "session_id": data.get("session_id", fname[:-5]),
                "label": data.get("label", ""),
                "msg_count": msg_count,
                "mtime": os.path.getmtime(path),
            })
        except Exception:
            pass
    return sorted(sessions, key=lambda x: x["mtime"], reverse=True)


def delete_session_file(session_id: str) -> None:
    path = get_session_file(session_id)
    if os.path.exists(path):
        os.remove(path)


# ── Runtime 호출 ──────────────────────────────────────
def generate_session_id() -> str:
    """uuid 2개 연결로 33자 이상 session_id 생성"""
    return f"{uuid.uuid4().hex[:16]}-{uuid.uuid4().hex[:17]}"


def invoke_runtime(prompt: str, session_id: str, actor_id: str) -> tuple[str, list[dict]]:
    """AgentCore Runtime 호출. Returns: (응답 텍스트, tool_calls 리스트)"""
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    # Memory에서 취향 정보를 가져와 prompt에 주입 (시맨틱 검색)
    memory_context = ""
    try:
        prefs = []
        # namespace 정확 매치 + namespacePath 하위 검색 모두 시도
        search_targets = [
            {"namespace": f"/users/{actor_id}/preferences"},
            {"namespace": f"/users/{actor_id}/preferences/"},
            {"namespace": f"/users/{actor_id}/facts"},
            {"namespace": f"/users/{actor_id}/facts/"},
            {"namespacePath": f"/users/{actor_id}/"},
        ]
        for target in search_targets:
            try:
                resp = client.retrieve_memory_records(
                    memoryId=MEMORY_ID,
                    **target,
                    searchCriteria={"searchQuery": prompt, "topK": 5}
                )
                records = resp.get("memoryRecordSummaries", [])
                if records:
                    print(f"[Memory] retrieve {target} → {len(records)}건 ✅")
                    for r in records:
                        text = r.get("content", {}).get("text", "")
                        if text and text not in prefs:
                            prefs.append(text)
                            print(f"[Memory]   - {text[:60]}")
                    break  # 결과 나오면 더 시도할 필요 없음
            except Exception:
                pass
        if not prefs:
            print(f"[Memory] ⚠️ 취향 0건 — prompt 주입 없음")
        else:
            memory_context = "[사용자 취향 정보 (Memory에서 조회됨)]\n" + "\n".join(f"- {p}" for p in prefs) + "\n\n위 취향을 반드시 반영하여 답변하세요.\n\n"
            print(f"[Memory] ✅ {len(prefs)}개 취향 주입")
    except Exception as e:
        print(f"[Memory] ❌ 오류: {type(e).__name__}: {e}")

    augmented_prompt = memory_context + prompt

    # 이전 대화 컨텍스트 주입 (후속 질문 이해용)
    history = st.session_state.get("messages", [])
    if history:
        recent = history[-6:]  # 최근 3턴(user+assistant) 
        conv_lines = []
        for m in recent:
            role = "사용자" if m["role"] == "user" else "어시스턴트"
            conv_lines.append(f"{role}: {m['content'][:200]}")
        conv_context = "[이전 대화]\n" + "\n".join(conv_lines) + "\n\n[현재 질문]\n"
        augmented_prompt = memory_context + conv_context + prompt

    payload = json.dumps({
        "prompt": augmented_prompt,
        "session_id": session_id,
        "actor_id": actor_id,
    }).encode("utf-8")

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=RUNTIME_ARN,
            payload=payload,
            contentType="application/json",
            accept="application/json",
            runtimeSessionId=session_id,
        )
    except client.exceptions.ThrottlingException:
        return "⚠️ 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.", []
    except Exception as e:
        error_name = type(e).__name__
        if "Timeout" in error_name or "timeout" in str(e).lower():
            return "⚠️ Runtime 응답 시간 초과. 다시 시도해 주세요.", []
        return f"⚠️ 오류 발생: {error_name} — {str(e)[:200]}", []

    body = response["response"].read().decode("utf-8")

    text_parts = []
    tool_calls = []
    tool_counter = 0

    for line in body.split("\n"):
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if not data_str:
            continue
        try:
            data = json.loads(data_str)
            evt = data.get("event", {})

            # 텍스트 델타
            cbd = evt.get("contentBlockDelta", {})
            delta = cbd.get("delta", {})
            if "text" in delta:
                text_parts.append(delta["text"])

            # 도구 호출 감지 (contentBlockStart → toolUse)
            cbs = evt.get("contentBlockStart", {})
            tool_use = cbs.get("start", {}).get("toolUse")
            if tool_use:
                tool_counter += 1
                tool_calls.append({
                    "order": tool_counter,
                    "name": tool_use.get("name", "unknown"),
                    "input": {},
                })

            # 도구 입력 파라미터 (contentBlockDelta → toolUse)
            tool_delta = delta.get("toolUse", {})
            if tool_delta and tool_calls:
                try:
                    inp = json.loads(tool_delta.get("input", "{}"))
                    tool_calls[-1]["input"] = inp
                except Exception:
                    pass

        except json.JSONDecodeError:
            pass

    result = "".join(text_parts)

    # 기존 방식 fallback: <!-- TOOL_CALLS: --> 주석에서도 파싱
    if not tool_calls:
        tool_calls_match = re.search(r"<!-- TOOL_CALLS:(.*?) -->", result, re.DOTALL)
        if tool_calls_match:
            try:
                parsed = json.loads(tool_calls_match.group(1))
                for i, tc in enumerate(parsed, 1):
                    tool_calls.append({"order": i, "name": tc.get("name", "unknown"), "input": tc.get("input", {})})
            except json.JSONDecodeError:
                pass
            result = re.sub(r"\n?<!-- TOOL_CALLS:.*? -->", "", result, flags=re.DOTALL)

    # 응답 내용에서 도구 호출 키워드 감지 (최후 수단)
    if not tool_calls:
        if "search_restaurants" in body:
            tool_calls.append({"order": 1, "name": "search_restaurants", "input": {}})
        if "get_menu" in body:
            tool_calls.append({"order": len(tool_calls)+1, "name": "get_menu", "input": {}})

    # <thinking> 태그 제거 (완전한 태그 + 불완전하게 잘린 경우 모두)
    result = re.sub(r"<thinking>.*?</thinking>\n?", "", result, flags=re.DOTALL)
    result = re.sub(r"<thinking>.*$", "", result, flags=re.DOTALL)

    return result.strip() or "응답 없음", tool_calls


# ── 식당 카드 UI ──────────────────────────────────────
def render_restaurant_cards(text: str, tool_calls: list[dict]):
    """search_restaurants 도구가 호출되었으면 식당 카드 표시"""
    has_search = any(tc.get("name") == "search_restaurants" for tc in tool_calls)
    if not has_search:
        return

    RESTAURANTS = {
        "트라토리아 벨라": {"category": "이탈리안", "price": "1.5~5.5만원", "location": "강남역", "mood": "로맨틱·데이트"},
        "스시 오마카세 하루": {"category": "일식", "price": "6~15만원", "location": "압구정역", "mood": "프리미엄·접대"},
        "강남 한우명가": {"category": "한식", "price": "3.5~7만원", "location": "강남역", "mood": "회식·가족모임"},
        "딤섬하우스 강남": {"category": "중식", "price": "1~3.5만원", "location": "강남역", "mood": "캐주얼·점심"},
        "르 비스트로": {"category": "프렌치", "price": "5~8만원", "location": "압구정역", "mood": "기념일·프로포즈"},
        "미소라멘 강남점": {"category": "라멘", "price": "1~1.3만원", "location": "강남역", "mood": "혼밥·가성비"},
        "더 그린 키친": {"category": "채식/비건", "price": "1.2~1.8만원", "location": "신논현역", "mood": "건강·캐주얼"},
        "서울갈비 강남본점": {"category": "한식", "price": "1.5~4.5만원", "location": "역삼역", "mood": "대형회식·40명룸"},
    }

    mentioned = [name for name in RESTAURANTS if name in text]
    if not mentioned:
        return

    st.markdown("---")
    st.markdown("#### 🏪 식당 상세 정보")

    cols = st.columns(min(len(mentioned), 3))
    for i, name in enumerate(mentioned[:6]):
        info = RESTAURANTS[name]
        with cols[i % 3]:
            st.markdown(f"""
<div style="border:1px solid #ddd; border-radius:12px; padding:16px; margin:4px 0; background:#fafafa;">
    <h4 style="margin:0 0 8px 0;">{name}</h4>
    <p style="margin:2px 0; font-size:14px;">🏷️ {info['category']}</p>
    <p style="margin:2px 0; font-size:14px;">💰 {info['price']}</p>
    <p style="margin:2px 0; font-size:14px;">📍 {info['location']}</p>
    <p style="margin:2px 0; font-size:14px;">✨ {info['mood']}</p>
</div>
""", unsafe_allow_html=True)


# ── 페이지 설정 ──────────────────────────────────────
st.set_page_config(page_title="DiningConcierge", page_icon="🍽️", layout="wide")

# ── 세션 상태 초기화 ──────────────────────────────────
if "actor_id" not in st.session_state:
    st.session_state.actor_id = "user-taemin"
if "current_session" not in st.session_state:
    st.session_state.current_session = generate_session_id()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "tool_logs" not in st.session_state:
    st.session_state.tool_logs = []
if "memory_cache" not in st.session_state:
    st.session_state.memory_cache = None
if "referenced_memories" not in st.session_state:
    st.session_state.referenced_memories = []
if "session_label" not in st.session_state:
    st.session_state.session_label = ""

# ── 사이드바 ─────────────────────────────────────────
with st.sidebar:
    st.header("🍽️ DiningConcierge")
    st.divider()

    # 세션 관리
    st.subheader("💬 세션 관리")
    st.text_input("👤 사용자 ID", key="actor_id_input",
                  value=st.session_state.actor_id,
                  on_change=lambda: setattr(st.session_state, "actor_id", st.session_state.actor_id_input))

    # 현재 세션 정보
    st.caption(f"현재: `{st.session_state.current_session[:16]}...` | {len(st.session_state.messages)//2}턴")

    # 세션 이름 지정
    new_label = st.text_input("세션 이름 (선택)", value=st.session_state.session_label,
                               placeholder="예: 데이트 식당 탐색", key="session_label_input")
    if new_label != st.session_state.session_label:
        st.session_state.session_label = new_label

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🆕 새 세션", use_container_width=True):
            # 현재 세션 저장
            if st.session_state.messages:
                save_session_to_file(
                    st.session_state.current_session,
                    st.session_state.messages,
                    st.session_state.session_label,
                )
            # 새 세션 시작
            st.session_state.current_session = generate_session_id()
            st.session_state.messages = []
            st.session_state.tool_logs = []
            st.session_state.referenced_memories = []
            st.session_state.session_label = ""
            st.rerun()
    with col2:
        if st.button("💾 저장", use_container_width=True):
            save_session_to_file(
                st.session_state.current_session,
                st.session_state.messages,
                st.session_state.session_label,
            )
            st.toast("세션이 저장되었습니다.")

    # 저장된 세션 목록
    saved = list_saved_sessions()
    if saved:
        st.markdown("**저장된 세션**")
        for s in saved[:8]:
            sid = s["session_id"]
            label = s["label"] or sid[:12] + "..."
            is_current = sid == st.session_state.current_session
            marker = "▶ " if is_current else ""
            col_btn, col_del = st.columns([4, 1])
            with col_btn:
                if st.button(f"{marker}{label} ({s['msg_count']}턴)",
                             key=f"sess_{sid}", use_container_width=True,
                             disabled=is_current):
                    # 현재 세션 저장 후 선택 세션으로 전환
                    if st.session_state.messages:
                        save_session_to_file(
                            st.session_state.current_session,
                            st.session_state.messages,
                            st.session_state.session_label,
                        )
                    data = load_session_from_file(sid)
                    st.session_state.current_session = sid
                    st.session_state.messages = data["messages"]
                    st.session_state.session_label = data.get("label", "")
                    st.session_state.tool_logs = []
                    st.session_state.referenced_memories = []
                    st.rerun()
            with col_del:
                if st.button("🗑️", key=f"del_{sid}"):
                    delete_session_file(sid)
                    if sid == st.session_state.current_session:
                        st.session_state.current_session = generate_session_id()
                        st.session_state.messages = []
                        st.session_state.tool_logs = []
                        st.session_state.session_label = ""
                    st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Memory 새로고침", use_container_width=True):
            st.session_state.memory_cache = None
            st.rerun()

    st.divider()

    # ── Memory 현황 ──────────────────────────────────
    st.subheader("🧠 Memory 현황")

    # Memory 조회 (캐시)
    if st.session_state.memory_cache is None:
        st.session_state.memory_cache = get_memory_status(st.session_state.actor_id)

    mem = st.session_state.memory_cache

    # 원본 대화 (Short-term)
    conversations = mem.get("conversations", [])
    # 인덱싱 완료 (Long-term)
    idx_pref = mem.get("indexed_preferences", [])
    idx_facts = mem.get("indexed_facts", [])
    total_indexed = len(idx_pref) + len(idx_facts)

    st.markdown(f"**대화 기록**: {len(conversations)//2}턴 | **추출된 기억**: {total_indexed}개")

    # 원본 대화 표시
    if conversations:
        user_convs = [c for c in conversations if c["role"] == "USER"]
        with st.expander(f"💬 원본 대화 ({len(user_convs)}개 질문)", expanded=False):
            for c in conversations:
                role_icon = "👤" if c["role"] == "USER" else "🤖"
                text = c["text"][:80]
                st.markdown(f"{role_icon} {text}")
                if c["role"] == "ASSISTANT":
                    st.caption(f"  세션: {c['session_id']} · {c['timestamp']}")
                    st.markdown("---")
    else:
        st.info("💡 대화하면 Memory에 자동 저장됩니다.\n\n"
                "예: '일식 좋아해', '매운 거 못 먹어'")

    # 인덱싱된 취향 (Long-term)
    if idx_pref:
        with st.expander(f"❤️ 추출된 취향 ({len(idx_pref)}개)", expanded=True):
            for r in idx_pref:
                content = r.get("content", {}).get("text", str(r))
                st.markdown(f"• {content[:100]}")

    # 인덱싱된 사실 (Long-term)
    if idx_facts:
        with st.expander(f"📝 추출된 사실 ({len(idx_facts)}개)", expanded=True):
            for r in idx_facts:
                content = r.get("content", {}).get("text", str(r))
                st.markdown(f"• {content[:100]}")

    if total_indexed == 0 and conversations:
        st.caption("⏳ 취향 추출 중... (인덱싱 완료 후 표시됩니다)")

    # 참조된 Memory
    if st.session_state.referenced_memories:
        st.divider()
        st.markdown("**💡 이번 대화에서 참조된 Memory:**")
        for mem_item in st.session_state.referenced_memories:
            st.markdown(f"• {mem_item}")

    st.divider()

    # ── 도구 호출 로그 ────────────────────────────────
    st.subheader("🔧 도구 호출 로그")
    if st.session_state.tool_logs:
        for log_entry in st.session_state.tool_logs[-15:]:
            icon = TOOL_ICONS.get(log_entry["name"], "🔧")
            st.markdown(f"`#{log_entry['order']}` {icon} **{log_entry['name']}**")
            if log_entry.get("input"):
                inp = log_entry["input"]
                if isinstance(inp, dict):
                    brief = ", ".join(f"{k}={v}" for k, v in list(inp.items())[:2])
                    st.caption(f"  → {brief[:60]}")
    else:
        st.caption("아직 도구 호출이 없습니다.")

    st.divider()

    # Runtime 상태
    st.subheader("⚙️ Runtime")
    st.markdown("🟢 READY · Memory 🟢 Deployed")
    st.caption(f"Memory ID: `{MEMORY_ID[:30]}...`")

# ── 메인 채팅 영역 ───────────────────────────────────
st.title("🍽️ 다이닝 컨시어지")
st.caption(f"세션: `{st.session_state.current_session[:20]}...` · 사용자: `{st.session_state.actor_id}`")

# 대화 히스토리 표시
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            render_restaurant_cards(msg["content"], msg["tool_calls"])

# 채팅 입력
if prompt := st.chat_input("질문을 입력하세요 (예: 강남 식당 추천해 주세요)"):
    # 사용자 메시지 표시
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # Runtime 호출
    with st.chat_message("assistant"):
        with st.spinner("다이닝 컨시어지가 답변을 준비하고 있습니다..."):
            # Web Search가 필요한 질문인지 감지
            web_search_keywords = ["날씨", "이벤트", "최근", "오늘", "지금", "실시간", "뉴스", "소식", "축제"]
            needs_web_search = any(kw in prompt for kw in web_search_keywords)

            web_context = ""
            if needs_web_search:
                with st.spinner("🌐 웹 검색 중..."):
                    web_result = web_search(prompt, max_results=3)
                    if web_result:
                        web_context = f"\n\n[실시간 웹 검색 결과]\n{web_result}\n\n위 웹 검색 결과를 참고하여 답변하세요.\n\n"
                        # 도구 로그에 추가
                        base_order = len(st.session_state.tool_logs)
                        st.session_state.tool_logs.append({
                            "order": base_order + 1,
                            "name": "WebSearch",
                            "input": {"query": prompt},
                        })

            final_prompt = web_context + prompt if web_context else prompt

            result, tool_calls = invoke_runtime(
                final_prompt,
                session_id=st.session_state.current_session,
                actor_id=st.session_state.actor_id,
            )

            # 응답 표시
            st.markdown(result)

            # 식당 카드 표시
            if tool_calls:
                render_restaurant_cards(result, tool_calls)

            # 도구 로그 업데이트
            for tc in tool_calls:
                st.session_state.tool_logs.append({
                    "order": len(st.session_state.tool_logs) + 1,
                    "name": tc.get("name", "unknown"),
                    "input": tc.get("input", {}),
                })

    # 메시지 저장
    st.session_state.messages.append({
        "role": "assistant",
        "content": result,
        "tool_calls": tool_calls,
    })

    # 대화를 Memory에 기록 → 자동 extraction으로 취향 추출
    event_id = save_conversation_to_memory(
        st.session_state.actor_id,
        prompt,
        result,
        st.session_state.current_session,
    )
    if event_id:
        st.session_state.memory_cache = None  # 캐시 갱신

    # 세션 파일 자동 저장
    save_session_to_file(
        st.session_state.current_session,
        st.session_state.messages,
        st.session_state.session_label,
    )

    # Memory 참조 확인 (응답 후 시맨틱 검색)
    if prompt:
        memories_used = search_memory(st.session_state.actor_id, prompt)
        if memories_used:
            st.session_state.referenced_memories = [
                f"[{m.get('_namespace', '?')}] {str(m.get('content', {}).get('text', ''))[:80]}"
                for m in memories_used[:5]
            ]
        else:
            # tracked records에서 직접 매칭 확인
            mem_cache = st.session_state.memory_cache or {}
            tracked = [r for r in mem_cache.get("tracked_records", []) if r]
            if tracked:
                st.session_state.referenced_memories = [
                    f"💾 {r.get('content', {}).get('text', '')[:80]}"
                    for r in tracked[:5]
                ]

    # Memory 캐시 갱신
    st.session_state.memory_cache = None

    st.rerun()
