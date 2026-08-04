"""
DiningConcierge — Streamlit 프로덕션 앱
- 채팅 UI (st.chat_input + st.chat_message)
- 도구 호출 로그 (사이드바)
- 식당 상세 카드 (검색 결과)
- 사이드바: Memory 현황 + 취향 요약 + Runtime 상태 + 세션 관리
- Memory 연동: 세션 간 취향 유지 검증
"""

import uuid
import re
import json
import streamlit as st
import boto3

# ── 설정 ──────────────────────────────────────────────
RUNTIME_ARN = "arn:aws:bedrock-agentcore:us-west-2:678498164624:runtime/DiningConcierge_DiningConcierge-aLEpSdHOiw"
MEMORY_ID = "DiningConcierge_dining_memory-R5zXit9OAR"
REGION = "us-west-2"
GATEWAY_WEB_SEARCH_URL = "https://dining-web-search-gateway-fiahbr5mdx.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"

# ── 도구 아이콘 매핑 ──────────────────────────────────
TOOL_ICONS = {
    "search_restaurants": "🔍",
    "get_menu": "📋",
    "check_reservation": "📅",
    "create_reservation": "✅",
    "estimate_cost": "💰",
    "web-search-tool___WebSearch": "🌐",
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
            name="web-search-tool___WebSearch",
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
    """Memory 현황 종합 조회 (list + retrieve + 직접 ID 조회)"""
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    result = {"indexed_preferences": [], "indexed_facts": [], "tracked_records": [], "error": None}

    # 1. list로 인덱싱 완료된 records 조회
    for ns_type in ["preferences", "facts"]:
        ns = f"/users/{actor_id}/{ns_type}"
        try:
            resp = client.list_memory_records(memoryId=MEMORY_ID, namespace=ns)
            result[f"indexed_{ns_type}"] = resp.get("memoryRecords", [])
        except Exception:
            pass
        # trailing slash도 시도
        try:
            resp2 = client.list_memory_records(memoryId=MEMORY_ID, namespace=f"{ns}/")
            result[f"indexed_{ns_type}"].extend(resp2.get("memoryRecords", []))
        except Exception:
            pass

    # 2. 로컬에 저장된 record ID로 직접 조회
    tracked_ids = st.session_state.get("memory_record_ids", [])
    for rec_id in tracked_ids:
        try:
            resp = client.get_memory_record(memoryId=MEMORY_ID, memoryRecordId=rec_id)
            record = resp.get("memoryRecord", {})
            if record:
                result["tracked_records"].append(record)
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
            for r in resp.get("memoryRecords", []):
                r["_namespace"] = ns.split("/")[-2] if ns.endswith("/") else ns.split("/")[-1]
                results.append(r)
        except Exception:
            pass

    return results


def save_preference_to_memory(actor_id: str, text: str) -> str | None:
    """취향을 직접 Memory Record로 저장 (비동기 전략 대신 직접 저장)"""
    import uuid as _uuid
    from datetime import datetime, timezone
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    try:
        resp = client.batch_create_memory_records(
            memoryId=MEMORY_ID,
            records=[{
                "requestIdentifier": str(_uuid.uuid4()),
                "namespaces": [f"/users/{actor_id}/preferences"],
                "content": {"text": text},
                "timestamp": datetime.now(timezone.utc),
            }]
        )
        successful = resp.get("successfulRecords", [])
        if successful:
            return successful[0].get("memoryRecordId")
    except Exception:
        pass
    return None


# ── Runtime 호출 ──────────────────────────────────────
def generate_session_id() -> str:
    """uuid 2개 연결로 33자 이상 session_id 생성"""
    return f"{uuid.uuid4().hex[:16]}-{uuid.uuid4().hex[:17]}"


def invoke_runtime(prompt: str, session_id: str, actor_id: str) -> tuple[str, list[dict]]:
    """AgentCore Runtime 호출. Returns: (응답 텍스트, tool_calls 리스트)"""
    client = boto3.client("bedrock-agentcore", region_name=REGION)

    # Memory에서 취향 정보를 가져와 prompt에 주입
    memory_context = ""
    tracked_ids = st.session_state.get("memory_record_ids", [])
    if tracked_ids:
        prefs = []
        for rec_id in tracked_ids:
            try:
                resp = client.get_memory_record(memoryId=MEMORY_ID, memoryRecordId=rec_id)
                record = resp.get("memoryRecord", {})
                text = record.get("content", {}).get("text", "")
                if text:
                    prefs.append(text)
            except Exception:
                pass
        if prefs:
            memory_context = "[사용자 취향 정보 (Memory에서 조회됨)]\n" + "\n".join(f"- {p}" for p in prefs) + "\n\n위 취향을 반드시 반영하여 답변하세요.\n\n"

    augmented_prompt = memory_context + prompt

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
    for line in body.split("\n"):
        if line.startswith("data:"):
            data_str = line[5:].strip()
            if not data_str:
                continue
            try:
                data = json.loads(data_str)
                evt = data.get("event", {})
                cbd = evt.get("contentBlockDelta", {})
                delta = cbd.get("delta", {})
                if "text" in delta:
                    text_parts.append(delta["text"])
            except json.JSONDecodeError:
                pass

    result = "".join(text_parts)

    # tool_calls 메타데이터 추출
    tool_calls = []
    tool_calls_match = re.search(r"<!-- TOOL_CALLS:(.*?) -->", result, re.DOTALL)
    if tool_calls_match:
        try:
            tool_calls = json.loads(tool_calls_match.group(1))
        except json.JSONDecodeError:
            pass
        result = re.sub(r"\n?<!-- TOOL_CALLS:.*? -->", "", result, flags=re.DOTALL)

    # <thinking> 태그 제거
    result = re.sub(r"<thinking>.*?</thinking>\n?", "", result, flags=re.DOTALL)

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
if "memory_record_ids" not in st.session_state:
    st.session_state.memory_record_ids = []

# ── 사이드바 ─────────────────────────────────────────
with st.sidebar:
    st.header("🍽️ DiningConcierge")
    st.divider()

    # 세션 관리
    st.subheader("💬 세션 관리")
    st.text_input("👤 사용자 ID", key="actor_id_input",
                  value=st.session_state.actor_id,
                  on_change=lambda: setattr(st.session_state, "actor_id", st.session_state.actor_id_input))

    st.caption(f"세션: `{st.session_state.current_session[:20]}...`")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🆕 새 대화", use_container_width=True):
            st.session_state.current_session = generate_session_id()
            st.session_state.messages = []
            st.session_state.tool_logs = []
            st.session_state.referenced_memories = []
            st.rerun()
    with col2:
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

    # 인덱싱 완료된 records
    idx_pref = mem.get("indexed_preferences", [])
    idx_facts = mem.get("indexed_facts", [])
    tracked = mem.get("tracked_records", [])

    total_indexed = len(idx_pref) + len(idx_facts)
    total_tracked = len(tracked)

    st.markdown(f"**인덱싱 완료**: {total_indexed}개 | **저장됨(대기)**: {total_tracked}개")

    # 직접 저장된 (tracked) records 표시
    if tracked:
        with st.expander(f"💾 저장된 취향 ({total_tracked}개)", expanded=True):
            for r in tracked:
                content = r.get("content", {}).get("text", str(r))
                ns_list = r.get("namespaces", [])
                ns_label = "preferences" if "preferences" in str(ns_list) else "facts"
                created = str(r.get("createdAt", ""))[:19]
                st.markdown(f"• **{content}**")
                st.caption(f"  📁 {ns_label} · ⏰ {created}")

    # 인덱싱 완료된 records
    if idx_pref:
        with st.expander(f"❤️ 취향 (인덱싱 완료, {len(idx_pref)}개)", expanded=True):
            for r in idx_pref:
                content = r.get("content", {}).get("text", str(r))
                st.markdown(f"• {content[:100]}")

    if idx_facts:
        with st.expander(f"📝 기억된 사실 ({len(idx_facts)}개)", expanded=True):
            for r in idx_facts:
                content = r.get("content", {}).get("text", str(r))
                st.markdown(f"• {content[:100]}")

    if total_indexed == 0 and total_tracked == 0:
        st.info("💡 취향을 입력하면 Memory에 직접 저장됩니다.\n\n"
                "예: '일식 좋아해', '매운 거 못 먹어'")

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
            base_order = len(st.session_state.tool_logs)
            for i, tc in enumerate(tool_calls, 1):
                st.session_state.tool_logs.append({
                    "order": base_order + i,
                    "name": tc.get("name", "unknown"),
                    "input": tc.get("input", {}),
                })

    # 메시지 저장
    st.session_state.messages.append({
        "role": "assistant",
        "content": result,
        "tool_calls": tool_calls,
    })

    # 취향 키워드 감지 → 직접 Memory에 저장
    preference_keywords = ["좋아해", "좋아해요", "좋아합니다", "좋아하", "선호",
                           "싫어해", "싫어", "못 먹", "못먹", "안 먹", "안먹",
                           "알레르기", "즐겨", "자주 먹"]
    if any(kw in prompt for kw in preference_keywords):
        rec_id = save_preference_to_memory(st.session_state.actor_id, prompt)
        if rec_id:
            st.session_state.memory_record_ids.append(rec_id)
            st.session_state.memory_cache = None  # 캐시 갱신

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
