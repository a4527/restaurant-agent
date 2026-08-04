"""
DiningConcierge 평가 스크립트 — Strands Evals
평가 케이스 3종 (각각 도구 호출 + 응답 내용 검증):
1. 이탈리안 식당 추천 → search_restaurants 호출 + 식당명 포함
2. 메뉴 조회 → get_menu 호출 + 메뉴/가격 포함
3. 조용한 일식당 추천 → search_restaurants 호출 + 일식 관련 키워드 포함
평균 점수 0.7 이상이면 PASS, 미만이면 FAIL (배포 차단)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app", "DiningConcierge"))

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands_evals import Case, Experiment
from strands_evals.evaluators import ToolCalled, Contains

from tools import search_restaurants, get_menu

# ── 시스템 프롬프트 ─────────────────────────────────
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


def create_agent() -> Agent:
    return Agent(
        model=BedrockModel(model_id="us.amazon.nova-lite-v1:0", region_name="us-west-2"),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_restaurants, get_menu],
        conversation_manager=NullConversationManager(),
    )


def run_task(case: Case) -> dict:
    """Agent 실행 → output + trajectory 반환"""
    agent = create_agent()
    result = agent(case.input)

    trajectory = []
    for msg in agent.messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            for content in msg.get("content", []):
                if isinstance(content, dict) and "toolUse" in content:
                    trajectory.append(content["toolUse"]["name"])

    return {
        "output": str(result),
        "trajectory": trajectory,
    }


# ── 3개의 실험 (케이스별 적합한 evaluator) ────────────
experiments = [
    {
        "name": "이탈리안 식당 추천",
        "case": Case(
            name="이탈리안 식당 추천",
            input="이탈리안 식당 추천해줘",
        ),
        "evaluators": [
            ToolCalled(tool_name="search_restaurants"),
            Contains(value="트라토리아", case_sensitive=False),
        ],
    },
    {
        "name": "메뉴 조회",
        "case": Case(
            name="메뉴 조회",
            input="서울갈비 강남본점 메뉴 알려줘",
        ),
        "evaluators": [
            ToolCalled(tool_name="get_menu"),
            Contains(value="갈비", case_sensitive=False),
        ],
    },
    {
        "name": "조용한 일식당 추천",
        "case": Case(
            name="조용한 일식당 추천",
            input="조용한 분위기의 일식당 추천해줘",
        ),
        "evaluators": [
            ToolCalled(tool_name="search_restaurants"),
            Contains(value="오마카세", case_sensitive=False),
        ],
    },
]


if __name__ == "__main__":
    print("=" * 60)
    print("DiningConcierge 평가 시작 (Strands Evals)")
    print("=" * 60)

    all_scores = []

    for exp_def in experiments:
        print(f"\n▶ 케이스: {exp_def['name']}")
        experiment = Experiment(
            cases=[exp_def["case"]],
            evaluators=exp_def["evaluators"],
        )
        report = experiment.run_evaluations(task=run_task)
        case_score = report.overall_score
        all_scores.append(case_score)
        print(f"  점수: {case_score:.4f} | 개별: {report.scores} | 통과: {report.test_passes}")

    # 전체 평균 계산
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0

    print(f"\n{'=' * 60}")
    print(f"전체 평균 점수: {avg_score:.4f}")
    print(f"케이스별 점수: {[f'{s:.2f}' for s in all_scores]}")
    print(f"{'=' * 60}")

    THRESHOLD = 0.7
    if avg_score >= THRESHOLD:
        print(f"\n✅ PASS — 평균 점수 {avg_score:.4f} >= {THRESHOLD}")
        sys.exit(0)
    else:
        print(f"\n❌ FAIL — 평균 점수 {avg_score:.4f} < {THRESHOLD}")
        sys.exit(1)
