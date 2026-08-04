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

# ── MCP 클라이언트 싱글턴 (앱 시작 시 한 번만 초기화) ──
_mcp_local: MCPClient | None = None
_mcp_web: MCPClient | None = None
_extra_tools: list = []
_tools_initialized = False


def _init_tools():
    """MCP 클라이언트 초기화 (최초 1회)"""
    global _mcp_local, _mcp_web, _extra_tools, _tools_initialized
    if _tools_initialized:
        return

    # MCP stdio (예약/비용)
    try:
        _mcp_local = MCPClient(lambda: stdio_client(server=MCP_SERVER_PARAMS))
        _mcp_local.start()
        _extra_tools.extend(_mcp_local.list_tools_sync())
        log.info(f"MCP stdio 도구 로드 완료: {len(_extra_tools)}개")
    except Exception as e:
        log.warning(f"MCP stdio 초기화 실패: {e}")

    # Web Search Gateway (MCP HTTP) → @tool로 래핑하여 이름 단순화
    if GATEWAY_WEB_SEARCH_URL:
        try:
            _mcp_web = MCPClient(lambda: streamablehttp_client(url=GATEWAY_WEB_SEARCH_URL))
            _mcp_web.start()
            web_tools = _mcp_web.list_tools_sync()

            # web-search___WebSearch 이름 문제 → 직접 @tool로 래핑
            from strands import tool as strands_tool

            @strands_tool
            def WebSearch(query: str, maxResults: int = 5) -> str:
                """실시간 웹 검색으로 날씨, 이벤트, 뉴스 등 최신 정보를 조회합니다.
                Args:
                    query: 검색 쿼리
                    maxResults: 최대 결과 수 (기본 5)
                """
                result = _mcp_web.call_tool_sync(
                    tool_use_id="websearch",
                    name="web-search___WebSearch",
                    arguments={"query": query, "maxResults": maxResults}
                )
                if result.get("status") == "success":
                    content = result.get("content", [])
                    if content:
                        return content[0].get("text", "검색 결과 없음")
                return "웹 검색 결과를 가져오지 못했습니다."

            _extra_tools.append(WebSearch)
            log.info("Web Search Gateway 연결 성공 (WebSearch 도구 래핑 완료)")
        except Exception as e:
            log.warning(f"Web Search Gateway 연결 실패: {e}")

    _tools_initialized = True

# ── 설정 ──────────────────────────────────────────────
MEMORY_ID = os.environ.get("MEMORY_ID", "")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
GATEWAY_WEB_SEARCH_URL = os.environ.get("GATEWAY_WEB_SEARCH_URL", "")


def _get_ssm_value(name: str) -> str:
    """환경변수 없을 때 SSM에서 읽기"""
    try:
        import boto3
        ssm = boto3.client("ssm", region_name=REGION)
        resp = ssm.get_parameter(Name=name)
        return resp["Parameter"]["Value"]
    except Exception:
        return ""


# 환경변수 없으면 SSM에서 읽기
if not MEMORY_ID:
    MEMORY_ID = _get_ssm_value("/dining/MEMORY_ID")
if not GATEWAY_WEB_SEARCH_URL:
    GATEWAY_WEB_SEARCH_URL = _get_ssm_value("/dining/GATEWAY_URL")

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
6. WebSearch: 실시간 웹 검색으로 최신 정보를 조회합니다

도구 호출 규칙:
- 식당 추천 시 반드시 search_restaurants를 호출하세요.
- 메뉴/가격 조회 시 반드시 get_menu를 호출하세요.
- 예약 가능 여부 질문 시에만 check_reservation을 호출하세요.
- create_reservation은 사용자가 명시적으로 "예약해줘", "예약할게"라고 요청한 경우에만 호출하세요. 추천이나 가능 여부 확인만 할 때는 절대 예약하지 마세요.
- 비용/가격 산정 시 반드시 estimate_cost를 호출하세요.
- 날씨, 현재 기온, 실시간 이벤트, 최신 뉴스, 오늘/지금 관련 질문은 반드시 WebSearch를 호출하세요.

식당 추천 필수 규칙:
- search_restaurants 도구 호출 결과에 있는 식당만 추천하세요.
- 도구 결과에 없는 식당명, 메뉴, 주소를 절대 지어내거나 추측하지 마세요.
- search_restaurants 결과가 0건이면 "조건에 맞는 식당을 찾지 못했습니다. 조건을 바꿔서 다시 검색해볼까요?"라고만 답하세요.
- 결과가 있어도 실제 반환된 식당만 언급하세요. 개수를 임의로 늘리지 마세요.

사용자 취향 활용 규칙:
- 사용자 취향 정보는 참고용으로만 사용하세요. 현재 요청을 최우선으로 반영하세요.
- "다른 거", "다른 종류", "변화를 주고 싶어" 등의 표현이 있으면 취향과 다른 새로운 옵션을 추천하세요.
- 취향 정보가 현재 요청과 충돌하면 현재 요청을 따르세요.

날짜/시간 해석:
- 날짜가 "내일"이면 오늘 날짜 + 1일, "오늘"이면 오늘 날짜로 해석하세요.
- 시간이 "저녁"이면 19:00, "점심"이면 12:00으로 해석하세요.
- 인원이 명시되지 않으면 2명으로 가정하세요.

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
            return "[사용자 이전 취향 (참고용, 현재 요청을 우선시하세요)]\n" + "\n".join(f"- {p}" for p in prefs) + "\n\n"
    except Exception as e:
        log.warning(f"Memory retrieve 실패: {e}")
    return ""


def delete_conflicting_memories(actor_id: str, user_text: str) -> None:
    """상반된 취향이 있으면 기존 항목 삭제"""
    if not MEMORY_ID:
        return
    NEGATION_WORDS = ["싫어", "싫다", "별로", "안 좋아", "안좋아", "취소", "못 먹", "못먹", "안 먹"]
    if not any(neg in user_text for neg in NEGATION_WORDS):
        return
    try:
        import boto3 as _boto3
        client = _boto3.client("bedrock-agentcore", region_name=REGION)
        for ns in [f"/users/{actor_id}/preferences", f"/users/{actor_id}/facts"]:
            resp = client.retrieve_memory_records(
                memoryId=MEMORY_ID, namespace=ns,
                searchCriteria={"searchQuery": user_text, "topK": 5}
            )
            for r in resp.get("memoryRecordSummaries", []):
                if r.get("score", 0) >= 0.60 and r.get("memoryRecordId"):
                    try:
                        client.delete_memory_record(
                            memoryId=MEMORY_ID,
                            memoryRecordId=r["memoryRecordId"]
                        )
                        log.info(f"상반된 취향 삭제: {r['memoryRecordId']}")
                    except Exception:
                        pass
    except Exception as e:
        log.warning(f"상반된 취향 삭제 실패: {e}")


def save_to_memory(actor_id: str, session_id: str, user_text: str, assistant_text: str) -> None:
    """대화를 Memory에 create_event로 저장"""
    if not MEMORY_ID:
        return
    delete_conflicting_memories(actor_id, user_text)
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

    # MCP 클라이언트 초기화 (최초 1회)
    _init_tools()

    prompt, session_id, actor_id = _extract_fields(payload)

    # Memory에서 취향 조회 → prompt에 주입
    memory_context = get_memory_context(actor_id, prompt)

    # 이전 대화 컨텍스트
    conv_context = payload.get("conversation_context", "")

    augmented_prompt = memory_context + conv_context + prompt

    # Agent 생성 (싱글턴 도구 사용)
    agent = create_agent(_extra_tools)
    full_response = []

    try:
        async for event in agent.stream_async(augmented_prompt):
            if not isinstance(event, dict) or "event" not in event:
                continue
            cbs = event["event"].get("contentBlockStart")
            if cbs is not None and not cbs.get("start"):
                continue
            cbd = event["event"].get("contentBlockDelta", {})
            text = cbd.get("delta", {}).get("text", "")
            if text:
                full_response.append(text)
            yield event
    finally:
        pass  # MCP 클라이언트 종료 안 함 (싱글턴 유지)

    # 대화를 Memory에 저장
    if full_response:
        response_text = "".join(full_response)
        save_to_memory(actor_id, session_id, prompt, response_text)


if __name__ == "__main__":
    app.run()
# Wed Aug  5 03:31:50 KST 2026
