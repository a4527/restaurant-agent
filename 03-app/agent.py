"""
강남 식당 도우미 에이전트 (Strands Agents SDK)
- 대화 세션을 로컬 JSON 파일로 저장/복원
- 도구 호출 로그 캡처 (UI 표시용)
- tools.py: search_restaurants, get_menu (KB retrieve 연동)
- mcp_server.py: check_reservation, create_reservation, estimate_cost (MCP stdio)
"""

import sys
import json
import os
from pathlib import Path
from typing import Any
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client

from tools import search_restaurants, get_menu

# ── 설정 ──────────────────────────────────────────────
SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)
DEFAULT_SESSION_FILE = SESSION_DIR / "default_session.json"

# ── MCP 서버 설정 ────────────────────────────────────
MCP_SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["mcp_server.py"],
)

# ── 시스템 프롬프트 ───────────────────────────────────
SYSTEM_PROMPT = """당신은 강남 지역 식당 추천 전문 도우미입니다.

사용 가능한 도구:
1. search_restaurants: 조건에 맞는 식당을 검색합니다 (카테고리 필터 가능)
2. get_menu: 특정 식당의 메뉴와 가격을 조회합니다
3. check_reservation: 식당의 예약 가능 여부를 확인합니다
4. create_reservation: 식당 예약을 생성합니다
5. estimate_cost: 식사 비용을 산정합니다

사용자가 식당 추천을 요청하면:
1. 먼저 search_restaurants로 조건에 맞는 식당을 검색하세요
2. 메뉴가 궁금하면 get_menu로 조회하세요
3. 예약 관련 질문이 있으면 check_reservation으로 확인하세요
4. 예약 요청 시 create_reservation으로 예약을 생성하세요
5. 비용이 궁금하면 estimate_cost로 산정하세요

답변은 한국어로, 친절하고 간결하게 해주세요.
날짜가 "내일"이면 2026-08-03, "오늘"이면 2026-08-02로 해석하세요.
시간이 "저녁"이면 19:00, "점심"이면 12:00으로 해석하세요.
인원이 명시되지 않으면 2명으로 가정하세요.
이전 대화 내용을 참고하여 "그 식당", "방금 추천한" 같은 대명사 참조를 해석하세요.
"""


# ── 도구 호출 로그 캡처 콜백 ──────────────────────────
class LoggingCallbackHandler:
    """도구 호출 로그를 캡처하는 콜백 핸들러"""

    def __init__(self):
        self.tool_count = 0
        self.tool_logs: list[dict] = []

    def __call__(self, **kwargs: Any) -> None:
        tool_use = (
            kwargs.get("event", {})
            .get("contentBlockStart", {})
            .get("start", {})
            .get("toolUse")
        )

        if tool_use:
            self.tool_count += 1
            tool_name = tool_use.get("name", "unknown")
            self.tool_logs.append({
                "order": self.tool_count,
                "tool": tool_name,
                "status": "호출됨",
            })

    def get_logs(self) -> list[dict]:
        return self.tool_logs

    def reset(self):
        self.tool_count = 0
        self.tool_logs = []


# ── 세션 저장/복원 ────────────────────────────────────
def save_session(messages: list, session_file: Path = DEFAULT_SESSION_FILE) -> None:
    """대화 메시지를 JSON 파일로 저장"""
    serializable = []
    for msg in messages:
        try:
            json.dumps(msg)
            serializable.append(msg)
        except (TypeError, ValueError):
            pass

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def load_session(session_file: Path = DEFAULT_SESSION_FILE) -> list:
    """JSON 파일에서 대화 메시지 복원"""
    if session_file.exists():
        with open(session_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def clear_session(session_file: Path = DEFAULT_SESSION_FILE) -> None:
    """세션 파일 삭제 (초기화)"""
    if session_file.exists():
        os.remove(session_file)


# ── Agent 생성 및 실행 ────────────────────────────────
def create_agent(messages: list = None, callback_handler=None):
    """MCP 클라이언트를 연결한 Agent 생성"""
    mcp_client = MCPClient(
        lambda: stdio_client(server=MCP_SERVER_PARAMS)
    )
    mcp_client.start()

    agent = Agent(
        system_prompt=SYSTEM_PROMPT,
        tools=[search_restaurants, get_menu, *mcp_client.list_tools_sync()],
        messages=messages or [],
        callback_handler=callback_handler,
    )
    return agent, mcp_client


def run_agent(query: str, session_file: Path = DEFAULT_SESSION_FILE) -> tuple[str, list[dict]]:
    """세션을 복원하고 질문을 처리한 뒤 세션 저장. (응답, 도구로그) 반환"""
    mcp_client = None
    callback = LoggingCallbackHandler()
    try:
        messages = load_session(session_file)
        agent, mcp_client = create_agent(messages, callback_handler=callback)
        response = agent(query)
        save_session(agent.messages, session_file)
        return str(response), callback.get_logs()
    finally:
        if mcp_client:
            mcp_client.stop(None, None, None)


# ── 직접 실행 시 테스트 ───────────────────────────────
if __name__ == "__main__":
    clear_session()
    query = "내일 저녁에 예약 가능한 강남역 이탈리안 식당 추천해 주세요. 4명이서 까르보나라 먹으면 얼마야?"
    print(f"질문: {query}")
    print("=" * 60)
    result, logs = run_agent(query)
    print(result)
    print("\n도구 호출 로그:")
    for log in logs:
        print(f"  #{log['order']} {log['tool']} — {log['status']}")
