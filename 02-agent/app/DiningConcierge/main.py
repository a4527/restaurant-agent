"""
DiningConcierge — AgentCore Runtime 최종본
도구:
  - search_restaurants: KB 벡터 검색
  - get_menu: KB 메뉴 조회
  - MCP stdio: check_reservation, create_reservation, estimate_cost
  - Web Search Gateway (MCP HTTP): 실시간 웹 검색
Memory:
  - 사용자 취향 조회 (retrieve_memory_records) → prompt 주입
  - 대화 저장 (create_event) → 자동 extraction
"""

import sys
import json
import os
import boto3
from datetime import datetime, timezone
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from tools import search_restaurants, get_menu

app = BedrockAgentCoreApp()
log = app.logger

# ── 설정 ──────────────────────────────────────────────
MEMORY_ID = os.environ.get("MEMORY_ID", "")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
GATEWAY_WEB_SEARCH_URL = os.environ.get("GATEWAY_WEB_SEARCH_URL", "")

# ── MCP 서버 파라미터 ─────────────────────────────────
MCP_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(os.path.dirname(__file__), "mcp_server.py")],
)

# ── 시스템 프롬프트 ───────────────────────────────────
SYSTEM_PROMPT = """당신은 강남 지역 식당 추천 전문 도우미 "다이닝 컨시어지"입니다.

사용 가능한 도구:
1. search_restaurants: 조건에 맞는 식당을 검색합니다 (카테고리, 분위기, 가격대 필터 가능)
2. get_menu: 특정 식당의 메뉴와 가격 정보를 조회합니다
3. check_reservation: 식당의 예약 가능 여부를 확인합니다
4. create_reservation: 식당 예약을 생성합니다
5. estimate_cost: 식사 비용을 산정합니다
6. WebSearch: 실시간 웹 검색으로 최신 정보를 조회합니다 (이벤트, 날씨, 최신 소식 등)

중요 규칙:
- 식당 추천 시 반드시 search_restaurants를 호출하세요.
- 메뉴/가격 조회 시 반드시 get_menu를 호출하세요.
- 예약 가능 여부 질문 시 반드시 check_reservation을 호출하세요.
- 예약 요청 시 반드시 create_reservation을 호출하세요.
- 비용/가격 산정 시 반드시 estimate_cost를 호출하세요.
- 날짜가 "내일"이면 오늘 날짜 + 1일, "오늘"이면 오늘 날짜로 해석하세요.
- 시간이 "저녁"이면 19:00, "점심"이면 12:00으로 해석하세요.
- 인원이 명시되지 않으면 2명으로 가정하세요.
- 도구 호출 없이 식당명이나 메뉴를 추측/지어내기 절대 금지합니다.

답변은 한국어로, 친절하고 간결하게 해주세요.
"""


# ── Memory 함수 ───────────────────────────────────────
def get_memory_context(actor_id: str, query: str) -> str:
    """Memory에서 사용자 취향 조회 → 컨텍스트 문자열 반환"""
    if not MEMORY_ID:
        return ""
    try:
        client = boto3.client("bedrock-agentcore", region_name=REGION)
        prefs = []
        for ns in [f"/users/{actor_id}/preferences", f"/users/{actor_id}/facts"]:
            resp = client.retrieve_memory_records(
                memoryId=MEMORY_ID,
                namespace=ns,
                searchCriteria={"searchQuery": query, "topK": 5}
            )
            for r in resp.get("memoryRecordSummaries", []):
                text = r.get("content", {}).get("text", "")
                if text and text not in prefs:
                    prefs.append(text)
        if prefs:
            return "[사용자 취향 정보]\n" + "\n".join(f"- {p}" for p in prefs) + "\n\n위 취향을 반드시 반영하여 답변하세요.\n\n"
    except Exception as e:
        log.warning(f"Memory retrieve 실패: {e}")
    return ""


def save_to_memory(actor_id: str, session_id: str, user_text: str, assistant_text: str) -> None:
    """대화를 Memory에 create_event로 저장"""
    if not MEMORY_ID:
        return
    try:
        client = boto3.client("bedrock-agentcore", region_name=REGION)
        client.create_event(
            memoryId=MEMORY_ID,
            actorId=actor_id,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[
                {"conversational": {"content": {"text": user_text}, "role": "USER"}},
                {"conversational": {"content": {"text": assistant_text}, "role": "ASSISTANT"}},
            ]
        )
    except Exception as e:
        log.warning(f"Memory save 실패: {e}")


# ── Agent 생성 ────────────────────────────────────────
def create_agent(extra_tools: list = None) -> Agent:
    tools = [search_restaurants, get_menu]
    if extra_tools:
        tools.extend(extra_tools)
    return Agent(
        model=load_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
        conversation_manager=NullConversationManager(),
    )


# ── 엔트리포인트 ─────────────────────────────────────
def _extract_fields(payload: dict) -> tuple[str, str, str]:
    """payload에서 (prompt, session_id, actor_id) 추출"""
    prompt = payload.get("prompt", "")
    if isinstance(payload.get("messages"), str):
        prompt = payload["messages"]
    session_id = payload.get("session_id", "default")
    actor_id = payload.get("actor_id", "anonymous")
    return prompt, session_id, actor_id


@app.entrypoint
async def invoke(payload, context):
    log.info("DiningConcierge 에이전트 호출 시작")

    prompt, session_id, actor_id = _extract_fields(payload)

    # Memory에서 취향 조회 → prompt에 주입
    memory_context = get_memory_context(actor_id, prompt)

    # 이전 대화 컨텍스트 (payload에서 전달되는 경우)
    conv_context = payload.get("conversation_context", "")

    augmented_prompt = memory_context + conv_context + prompt

    # MCP 클라이언트들 초기화
    mcp_clients = []
    extra_tools = []

    # 1. MCP stdio (예약/비용)
    try:
        mcp_local = MCPClient(lambda: stdio_client(server=MCP_SERVER_PARAMS))
        mcp_local.start()
        mcp_clients.append(mcp_local)
        extra_tools.extend(mcp_local.list_tools_sync())
        log.info(f"MCP stdio 도구 로드: {[t.tool_name for t in mcp_local.list_tools_sync()]}")
    except Exception as e:
        log.warning(f"MCP stdio 초기화 실패: {e}")

    # 2. Web Search Gateway (MCP HTTP)
    if GATEWAY_WEB_SEARCH_URL:
        try:
            mcp_web = MCPClient(lambda: streamablehttp_client(url=GATEWAY_WEB_SEARCH_URL))
            mcp_web.start()
            mcp_clients.append(mcp_web)
            extra_tools.extend(mcp_web.list_tools_sync())
            log.info("Web Search Gateway 연결 성공")
        except Exception as e:
            log.warning(f"Web Search Gateway 연결 실패: {e}")

    # Agent 생성 및 실행
    agent = create_agent(extra_tools)
    full_response = []

    try:
        async for event in agent.stream_async(augmented_prompt):
            if not isinstance(event, dict) or "event" not in event:
                continue
            cbs = event["event"].get("contentBlockStart")
            if cbs is not None and not cbs.get("start"):
                continue
            # 텍스트 수집 (Memory 저장용)
            cbd = event["event"].get("contentBlockDelta", {})
            text = cbd.get("delta", {}).get("text", "")
            if text:
                full_response.append(text)
            yield event
    finally:
        # MCP 클라이언트 종료
        for mcp in mcp_clients:
            try:
                mcp.stop(None, None, None)
            except Exception:
                pass

    # 대화를 Memory에 저장 (비동기 extraction 트리거)
    if full_response:
        response_text = "".join(full_response)
        save_to_memory(actor_id, session_id, prompt, response_text)


if __name__ == "__main__":
    app.run()
# Wed Aug  5 03:31:50 KST 2026
