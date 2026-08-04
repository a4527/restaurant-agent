"""
DiningConcierge — AgentCore Runtime (Pipeline Edition)
도구: search_restaurants (카탈로그 검색)
특징: 추측 금지 프롬프트, Memory/Gateway 의존 없음
"""

import json
from strands import Agent
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from tools import search_restaurants, get_menu

app = BedrockAgentCoreApp()
log = app.logger

# ── 시스템 프롬프트 (추측 금지) ───────────────────────
SYSTEM_PROMPT = """당신은 강남 지역 식당 추천 전문 도우미 "다이닝 컨시어지"입니다.

사용 가능한 도구:
1. search_restaurants: 조건에 맞는 식당을 검색합니다 (카테고리 필터 가능)
2. get_menu: 특정 식당의 메뉴와 가격 정보를 조회합니다

중요 규칙:
- 반드시 도구(search_restaurants, get_menu)를 호출하여 실제 데이터를 기반으로 답변하세요.
- 도구 호출 없이 식당명이나 메뉴를 추측/지어내기 절대 금지합니다.
- 도구 검색 결과에 없는 식당은 언급하지 마세요.
- 식당 추천 시 식당명, 카테고리, 가격대, 위치, 분위기를 구조화해서 답변하세요.

답변은 한국어로, 친절하고 간결하게 해주세요.
"""

# ── Agent 싱글턴 ─────────────────────────────────────
_agent = None


def _get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=[search_restaurants, get_menu],
            conversation_manager=NullConversationManager(),
        )
    return _agent


# ── 엔트리포인트 ─────────────────────────────────────
def _extract_prompt(payload: dict):
    if "messages" in payload:
        return payload["messages"]
    return payload.get("prompt", "")


@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking DiningConcierge Agent (Pipeline Edition)...")

    agent = _get_agent()
    prompt = _extract_prompt(payload)

    async for event in agent.stream_async(prompt):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
