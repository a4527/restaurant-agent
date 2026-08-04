"""
강남 식당 도우미 도구 (Strands Agents SDK)
- search_restaurants: 식당 검색 (KB retrieve + 카테고리 필터)
- get_menu: 메뉴/가격 조회 (KB retrieve)
"""

import boto3
from strands import tool

# ── 설정 ──────────────────────────────────────────────
KB_ID = "RIFBMADYWG"
REGION = "us-west-2"
NUM_RESULTS = 5

_client = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── 공통 KB 검색 함수 ─────────────────────────────────
def _retrieve(query: str, filter_config: dict | None = None) -> list[dict]:
    """KB retrieve API 호출 공통 함수"""
    vector_config: dict = {"numberOfResults": NUM_RESULTS}
    if filter_config:
        vector_config["filter"] = filter_config

    response = _client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": vector_config},
    )

    results = []
    for item in response.get("retrievalResults", []):
        uri = item.get("location", {}).get("s3Location", {}).get("uri", "")
        filename = uri.split("/")[-1] if uri else "unknown"
        text = item.get("content", {}).get("text", "")
        score = item.get("score", 0)
        results.append({"file": filename, "text": text, "score": score})

    return results


# ── 도구 1: 식당 검색 ─────────────────────────────────
@tool
def search_restaurants(query: str, category: str = "") -> str:
    """강남 지역 식당을 검색합니다.

    Bedrock Knowledge Base를 사용하여 질문에 맞는 식당을 벡터 검색합니다.
    카테고리 필터를 지정하면 해당 카테고리 식당만 검색합니다.

    Args:
        query: 검색 질문 (예: "데이트하기 좋은 식당", "회식 가능한 곳")
        category: 카테고리 필터 (한식, 일식, 중식, 이탈리안, 프렌치, 채식/비건). 빈 문자열이면 전체 검색.

    Returns:
        검색된 식당 정보 문자열 (식당명, 관련 내용, 유사도 점수 포함)
    """
    filter_config = None
    if category:
        filter_config = {"equals": {"key": "category", "value": category}}

    results = _retrieve(query, filter_config)

    if not results:
        return "조건에 맞는 식당을 찾지 못했습니다."

    output_lines = []
    for i, r in enumerate(results, 1):
        output_lines.append(f"[{i}] (score: {r['score']:.4f}) {r['file']}")
        output_lines.append(f"    {r['text'][:200]}")
        output_lines.append("")

    return "\n".join(output_lines)


# ── 도구 2: 메뉴 조회 ─────────────────────────────────
@tool
def get_menu(restaurant_name: str) -> str:
    """특정 식당의 메뉴와 가격 정보를 조회합니다.

    Bedrock Knowledge Base에서 식당명으로 검색하여 메뉴 정보를 반환합니다.

    Args:
        restaurant_name: 식당 이름 (예: "트라토리아 벨라", "서울갈비 강남본점")

    Returns:
        해당 식당의 메뉴와 가격 정보 문자열
    """
    query = f"{restaurant_name} 메뉴 가격"
    results = _retrieve(query)

    if not results:
        return f"'{restaurant_name}'의 메뉴 정보를 찾지 못했습니다."

    relevant = [r for r in results if restaurant_name in r["text"]]
    if not relevant:
        relevant = results[:2]

    output_lines = [f"📋 {restaurant_name} 메뉴 정보\n"]
    for r in relevant:
        output_lines.append(f"[출처: {r['file']}]")
        output_lines.append(r["text"][:400])
        output_lines.append("")

    return "\n".join(output_lines)


# ── 직접 실행 시 테스트 ───────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("테스트 1: search_restaurants (이탈리안)")
    print("=" * 60)
    print(search_restaurants(query="데이트하기 좋은 식당", category="이탈리안"))

    print("\n" + "=" * 60)
    print("테스트 2: get_menu (트라토리아 벨라)")
    print("=" * 60)
    print(get_menu(restaurant_name="트라토리아 벨라"))
