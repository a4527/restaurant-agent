"""
eval_gate.py 배포 임계값 최적화 테스트

현재 eval_gate.py의 테스트 케이스를 여러 번 반복 실행하여
점수 분포를 파악하고 최적 임계값을 추천합니다.

실행: python3 test_eval_threshold.py
옵션: python3 test_eval_threshold.py --runs 5  (반복 횟수, 기본 3)
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "02-agent", "app", "DiningConcierge"))

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands_evals import Case, Experiment
from strands_evals.evaluators import ToolCalled, Contains

from tools import search_restaurants, get_menu

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

# ── 테스트 케이스 ────────────────────────────────────
EXPERIMENTS = [
    {
        "name": "이탈리안 식당 추천",
        "case": Case(name="이탈리안", input="이탈리안 식당 추천해줘"),
        "evaluators": [
            ToolCalled(tool_name="search_restaurants"),
            Contains(value="트라토리아", case_sensitive=False),
        ],
    },
    {
        "name": "메뉴 조회",
        "case": Case(name="메뉴조회", input="서울갈비 강남본점 메뉴 알려줘"),
        "evaluators": [
            ToolCalled(tool_name="get_menu"),
            Contains(value="갈비", case_sensitive=False),
        ],
    },
    {
        "name": "조용한 일식당 추천",
        "case": Case(name="일식당", input="조용한 분위기의 일식당 추천해줘"),
        "evaluators": [
            ToolCalled(tool_name="search_restaurants"),
            Contains(value="오마카세", case_sensitive=False),
        ],
    },
]

THRESHOLDS = [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9]


def create_agent() -> Agent:
    return Agent(
        model=BedrockModel(model_id="us.amazon.nova-lite-v1:0", region_name="us-west-2"),
        system_prompt=SYSTEM_PROMPT,
        tools=[search_restaurants, get_menu],
        conversation_manager=NullConversationManager(),
    )


def run_task(case: Case) -> dict:
    agent = create_agent()
    result = agent(case.input)
    trajectory = []
    for msg in agent.messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            for content in msg.get("content", []):
                if isinstance(content, dict) and "toolUse" in content:
                    trajectory.append(content["toolUse"]["name"])
    return {"output": str(result), "trajectory": trajectory}


def run_once() -> dict[str, float]:
    """한 번 전체 실험 실행 → {케이스명: 점수} 반환"""
    scores = {}
    for exp_def in EXPERIMENTS:
        experiment = Experiment(
            cases=[exp_def["case"]],
            evaluators=exp_def["evaluators"],
        )
        report = experiment.run_evaluations(task=run_task)
        scores[exp_def["name"]] = report.overall_score
    return scores


def run_threshold_test(num_runs: int):
    print("=" * 65)
    print("eval_gate.py 배포 임계값 최적화 테스트")
    print("=" * 65)
    print(f"케이스 수: {len(EXPERIMENTS)}개 | 반복 횟수: {num_runs}회")
    print()

    # 1. num_runs 회 반복 실행
    all_runs = []
    for i in range(num_runs):
        print(f"▶ 실행 {i+1}/{num_runs}...")
        run_scores = run_once()
        avg = sum(run_scores.values()) / len(run_scores)
        all_runs.append({"scores": run_scores, "avg": avg})

        for name, score in run_scores.items():
            print(f"  {name}: {score:.4f}")
        print(f"  → 평균: {avg:.4f}")
        print()

    # 2. 통계 계산
    avgs = [r["avg"] for r in all_runs]
    min_avg = min(avgs)
    max_avg = max(avgs)
    mean_avg = sum(avgs) / len(avgs)
    variance = sum((x - mean_avg) ** 2 for x in avgs) / len(avgs)
    std_dev = variance ** 0.5

    print("=" * 65)
    print("📊 점수 통계")
    print("-" * 65)

    # 케이스별 통계
    for exp_def in EXPERIMENTS:
        name = exp_def["name"]
        case_scores = [r["scores"][name] for r in all_runs]
        c_min = min(case_scores)
        c_max = max(case_scores)
        c_mean = sum(case_scores) / len(case_scores)
        print(f"  {name}")
        print(f"    평균={c_mean:.4f} | 최소={c_min:.4f} | 최대={c_max:.4f}")

    print()
    print(f"  전체 평균: {mean_avg:.4f} (±{std_dev:.4f})")
    print(f"  범위: {min_avg:.4f} ~ {max_avg:.4f}")

    # 3. 임계값별 통과율
    print()
    print("=" * 65)
    print("📈 임계값별 PASS율")
    print("-" * 65)
    print(f"{'임계값':>8} | {'PASS율':>8} | {'PASS횟수':>8} | {'판단'}")
    print("-" * 65)

    best_threshold = None
    for threshold in THRESHOLDS:
        passes = sum(1 for avg in avgs if avg >= threshold)
        pass_rate = passes / num_runs

        if pass_rate >= 0.9 and best_threshold is None:
            best_threshold = threshold

        judgment = ""
        if pass_rate == 1.0:
            judgment = "✅ 항상 통과"
        elif pass_rate >= 0.9:
            judgment = "✅ 거의 항상 통과"
        elif pass_rate >= 0.7:
            judgment = "⚠️  가끔 실패"
        elif pass_rate >= 0.5:
            judgment = "⚠️  자주 실패"
        else:
            judgment = "❌ 대부분 실패"

        marker = " ★" if threshold == best_threshold else ""
        print(f"  {threshold:>6.2f}   | {pass_rate:>7.1%} | {passes:>5}/{num_runs}   | {judgment}{marker}")

    print()
    print("=" * 65)

    if best_threshold:
        print(f"✅ 추천 임계값: {best_threshold}")
        print(f"   이 임계값에서 {num_runs}회 중 90% 이상 PASS합니다.")
        print(f"   실제 점수 범위: {min_avg:.4f} ~ {max_avg:.4f}")
    else:
        print(f"⚠️  90% PASS를 만족하는 임계값 없음")
        print(f"   현재 점수가 불안정합니다 (범위: {min_avg:.4f} ~ {max_avg:.4f})")
        print(f"   에이전트 프롬프트나 evaluator를 검토하세요.")

    print()
    print("eval_gate.py에서 임계값을 업데이트하려면:")
    if best_threshold:
        print(f"  THRESHOLD = {best_threshold}")

    return best_threshold


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3, help="반복 실행 횟수 (기본: 3)")
    args = parser.parse_args()

    run_threshold_test(num_runs=args.runs)
