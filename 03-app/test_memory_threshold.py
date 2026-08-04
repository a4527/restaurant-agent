"""
Memory 중복 감지 임계값 최적화 테스트

실제 Memory에 저장하지 않고 Titan Embed를 직접 호출하여
코사인 유사도를 계산합니다.

실행: python3 test_memory_threshold.py
"""

import boto3
import json
import math

REGION = "us-west-2"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"

# ── 테스트 케이스 ────────────────────────────────────
# (텍스트A, 텍스트B, 기대결과)
# "duplicate" → 중복으로 판단해야 함 (저장 스킵)
# "different" → 다른 내용으로 판단해야 함 (저장 허용)

TEST_CASES = [
    # ── 중복이어야 하는 쌍 ──────────────────────────
    ("일식 좋아해",           "일식을 좋아합니다",              "duplicate"),
    ("일식 좋아해",           "일식을 즐겨 먹어",               "duplicate"),
    ("매운 음식 못 먹어",     "매운 거 못 먹어요",              "duplicate"),
    ("매운 음식 못 먹어",     "매운 음식은 못 먹습니다",        "duplicate"),
    ("조용한 분위기 선호해",  "조용한 곳을 좋아해",             "duplicate"),
    ("스테이크 좋아해",       "스테이크를 즐겨 먹어요",         "duplicate"),
    ("해산물 알레르기 있어",  "해산물 알레르기가 있습니다",     "duplicate"),
    ("와인 즐겨 마셔",        "와인을 좋아해요",                "duplicate"),

    # ── 다른 내용이어야 하는 쌍 ─────────────────────
    ("일식 좋아해",           "매운 음식 못 먹어",              "different"),
    ("일식 좋아해",           "스테이크 좋아해",                "different"),
    ("일식 좋아해",           "조용한 분위기 선호해",           "different"),
    ("일식 좋아해",           "해산물 알레르기 있어",           "different"),
    ("스테이크 좋아해",       "조용한 분위기 선호해",           "different"),
    ("스테이크 좋아해",       "와인 즐겨 마셔",                 "different"),
    ("매운 음식 못 먹어",     "해산물 알레르기 있어",           "different"),
    ("예산 인당 5만원",       "일식 좋아해",                   "different"),
]

THRESHOLDS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]


def get_embedding(client, text: str) -> list[float]:
    """Titan Embed로 텍스트 임베딩 벡터 반환"""
    resp = client.invoke_model(
        modelId=EMBED_MODEL_ID,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(resp["body"].read())
    return body["embedding"]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도 계산"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def run_threshold_test():
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)

    dup_total = sum(1 for _, _, e in TEST_CASES if e == "duplicate")
    diff_total = sum(1 for _, _, e in TEST_CASES if e == "different")

    print("=" * 65)
    print("Memory 중복 감지 임계값 최적화 테스트 (Titan Embed)")
    print("=" * 65)
    print(f"테스트 케이스: {len(TEST_CASES)}개 (중복 {dup_total}개 / 다른내용 {diff_total}개)")
    print("※ 실제 Memory에 저장하지 않음 (임베딩 직접 비교)")
    print()

    # 1. 모든 텍스트 임베딩 (중복 호출 방지)
    print("📡 임베딩 계산 중...")
    texts = set()
    for a, b, _ in TEST_CASES:
        texts.add(a)
        texts.add(b)

    embed_cache = {}
    for i, text in enumerate(texts):
        embed_cache[text] = get_embedding(bedrock, text)
        print(f"  [{i+1}/{len(texts)}] '{text}'")

    # 2. 유사도 점수 계산
    print()
    print("📊 유사도 점수")
    print("-" * 65)
    scores = []
    for text_a, text_b, expected in TEST_CASES:
        score = cosine_similarity(embed_cache[text_a], embed_cache[text_b])
        scores.append(score)
        label = "🔴 중복" if expected == "duplicate" else "🟢 다름"
        print(f"  {label} | {score:.4f} | '{text_a[:18]}' ↔ '{text_b[:18]}'")

    # 3. 임계값별 정확도
    print()
    print("=" * 65)
    print("📈 임계값별 정확도")
    print("-" * 65)
    print(f"{'임계값':>8} | {'정확도':>6} | {'중복감지':>8} | {'다름통과':>8} | {'오탐(FP)':>8} | {'누락(FN)':>8}")
    print("-" * 65)

    best_threshold = None
    best_f1 = -1.0
    results = {}

    for threshold in THRESHOLDS:
        tp = fp = tn = fn = 0

        for score, (_, _, expected) in zip(scores, TEST_CASES):
            predicted = "duplicate" if score >= threshold else "different"
            if expected == "duplicate":
                if predicted == "duplicate":
                    tp += 1
                else:
                    fn += 1
            else:
                if predicted == "different":
                    tn += 1
                else:
                    fp += 1

        accuracy = (tp + tn) / len(TEST_CASES)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        dup_recall = tp / dup_total if dup_total > 0 else 0
        diff_acc = tn / diff_total if diff_total > 0 else 0

        results[threshold] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn,
                              "accuracy": accuracy, "f1": f1}

        # F1 기준으로 최적 선택 (정밀도와 재현율 균형)
        marker = ""
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = threshold
            marker = " ★"

        print(f"  {threshold:>6.2f}   | {accuracy:>5.1%} | {dup_recall:>7.1%} | {diff_acc:>7.1%} | {fp:>8d} | {fn:>8d}{marker}")

    print()
    print("=" * 65)
    r = results[best_threshold]
    print(f"✅ 추천 임계값: {best_threshold}")
    print(f"   정확도: {r['accuracy']:.1%} | F1: {best_f1:.4f}")
    print(f"   올바른 중복 감지: {r['tp']}/{dup_total} | 올바른 통과: {r['tn']}/{diff_total}")
    if r["fp"] > 0:
        print(f"   ⚠️  오탐 {r['fp']}건 (다른 내용인데 중복으로 판단):")
        for score, (a, b, expected) in zip(scores, TEST_CASES):
            if expected == "different" and score >= best_threshold:
                print(f"      score={score:.4f} | '{a}' ↔ '{b}'")
    if r["fn"] > 0:
        print(f"   ⚠️  누락 {r['fn']}건 (중복인데 통과됨):")
        for score, (a, b, expected) in zip(scores, TEST_CASES):
            if expected == "duplicate" and score < best_threshold:
                print(f"      score={score:.4f} | '{a}' ↔ '{b}'")

    print()
    print(f"app.py에서 임계값을 업데이트하려면:")
    print(f'  if r.get("score", 0) >= {best_threshold}:')

    return best_threshold


if __name__ == "__main__":
    best = run_threshold_test()
