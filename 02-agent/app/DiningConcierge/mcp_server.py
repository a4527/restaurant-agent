"""
강남 식당 MCP 서버 (stdio 방식)
- check_reservation: 예약 가능 여부 조회
- create_reservation: 예약 생성
- estimate_cost: 식사 비용 산정 (인원 × 메뉴 가격 + 서비스 차지)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("restaurant-services")

# ── 예약 데이터 (시뮬레이션) ──────────────────────────
RESTAURANT_CAPACITY = {
    "트라토리아 벨라": {"max_seats": 20, "rooms": 2},
    "스시 오마카세 하루": {"max_seats": 8, "rooms": 0},
    "강남 한우명가": {"max_seats": 30, "rooms": 5},
    "딤섬하우스 강남": {"max_seats": 15, "rooms": 1},
    "르 비스트로": {"max_seats": 12, "rooms": 1},
    "미소라멘 강남점": {"max_seats": 4, "rooms": 0},
    "더 그린 키친": {"max_seats": 10, "rooms": 0},
    "서울갈비 강남본점": {"max_seats": 40, "rooms": 3},
}

BOOKED = {
    ("트라토리아 벨라", "2026-08-02", "19:00"): 14,
    ("강남 한우명가", "2026-08-02", "19:00"): 28,
    ("서울갈비 강남본점", "2026-08-02", "19:00"): 20,
    ("스시 오마카세 하루", "2026-08-02", "19:00"): 8,
    ("딤섬하우스 강남", "2026-08-03", "12:00"): 5,
}

RESERVATIONS: list[dict] = []

# ── 메뉴 가격 데이터 (비용 산정용) ────────────────────
MENU_PRICES = {
    "트라토리아 벨라": {
        "마르게리타 피자": 18000, "까르보나라": 22000, "해산물 리조또": 28000,
        "티라미수": 12000, "트러플 파스타": 35000, "오소부코": 55000,
        "런치 세트": 25000,
    },
    "스시 오마카세 하루": {
        "런치 오마카세": 60000, "디너 오마카세": 90000, "프리미엄 오마카세": 150000,
    },
    "강남 한우명가": {
        "한우 등심 세트": 65000, "한우 갈비 세트": 70000, "육회": 35000,
        "된장찌개": 12000, "회식 패키지": 55000,
    },
    "딤섬하우스 강남": {
        "하가우": 12000, "슈마이": 10000, "샤오롱바오": 15000,
        "딤섬 세트 A": 25000, "딤섬 세트 B": 35000, "런치 세트": 15000,
    },
    "르 비스트로": {
        "런치 코스": 50000, "디너 코스 A": 70000, "디너 코스 B": 80000,
        "와인 페어링": 30000,
    },
    "미소라멘 강남점": {
        "돈코츠 라멘": 12000, "미소 라멘": 11000, "츠케멘": 13000,
        "교자": 6000, "차슈덮밥": 10000,
    },
    "더 그린 키친": {
        "비건 버거": 16000, "퀴노아 샐러드 볼": 14000, "두부 스테이크": 18000,
        "스무디 볼": 12000, "비건 파스타": 17000,
    },
    "서울갈비 강남본점": {
        "양념갈비": 35000, "생갈비": 45000, "갈비탕": 15000,
        "비빔냉면": 12000, "회식 패키지": 35000,
    },
}

# 서비스 차지 (식당별)
SERVICE_CHARGE = {
    "트라토리아 벨라": 0.0,
    "스시 오마카세 하루": 0.10,
    "강남 한우명가": 0.0,
    "딤섬하우스 강남": 0.0,
    "르 비스트로": 0.10,
    "미소라멘 강남점": 0.0,
    "더 그린 키친": 0.0,
    "서울갈비 강남본점": 0.0,
}


# ── 도구 1: 예약 가능 여부 조회 ───────────────────────
@mcp.tool()
def check_reservation(
    restaurant_name: str,
    date: str,
    time: str,
    party_size: int,
) -> str:
    """식당 예약 가능 여부를 조회합니다.

    Args:
        restaurant_name: 식당 이름 (예: "트라토리아 벨라")
        date: 예약 날짜 (YYYY-MM-DD 형식)
        time: 예약 시간 (HH:MM 형식)
        party_size: 예약 인원 수

    Returns:
        예약 가능 여부, 남은 좌석 수, 식당 정보
    """
    if restaurant_name not in RESTAURANT_CAPACITY:
        available = ", ".join(RESTAURANT_CAPACITY.keys())
        return f"'{restaurant_name}' 식당을 찾을 수 없습니다. 등록된 식당: {available}"

    capacity = RESTAURANT_CAPACITY[restaurant_name]
    max_seats = capacity["max_seats"]
    rooms = capacity["rooms"]

    booked = BOOKED.get((restaurant_name, date, time), 0)
    remaining = max_seats - booked

    if remaining <= 0:
        return (
            f"❌ 예약 불가\n"
            f"식당: {restaurant_name}\n"
            f"날짜: {date} {time}\n"
            f"사유: 해당 시간대 만석입니다."
        )

    if party_size > remaining:
        return (
            f"❌ 예약 불가\n"
            f"식당: {restaurant_name}\n"
            f"날짜: {date} {time}\n"
            f"요청 인원: {party_size}명 / 남은 좌석: {remaining}석\n"
            f"사유: 인원 초과"
        )

    return (
        f"✅ 예약 가능\n"
        f"식당: {restaurant_name}\n"
        f"날짜: {date} {time}\n"
        f"요청 인원: {party_size}명\n"
        f"남은 좌석: {remaining}석\n"
        f"프라이빗 룸: {'있음 (' + str(rooms) + '개)' if rooms > 0 else '없음'}"
    )


# ── 도구 2: 예약 생성 ─────────────────────────────────
@mcp.tool()
def create_reservation(
    restaurant_name: str,
    date: str,
    time: str,
    party_size: int,
    customer_name: str,
) -> str:
    """식당 예약을 생성합니다. 예약 가능 여부를 확인한 뒤 예약을 확정합니다.

    Args:
        restaurant_name: 식당 이름
        date: 예약 날짜 (YYYY-MM-DD 형식)
        time: 예약 시간 (HH:MM 형식)
        party_size: 예약 인원 수
        customer_name: 예약자 이름

    Returns:
        예약 확정 결과 (예약 번호 포함) 또는 실패 사유
    """
    if restaurant_name not in RESTAURANT_CAPACITY:
        available = ", ".join(RESTAURANT_CAPACITY.keys())
        return f"'{restaurant_name}' 식당을 찾을 수 없습니다. 등록된 식당: {available}"

    capacity = RESTAURANT_CAPACITY[restaurant_name]
    max_seats = capacity["max_seats"]

    booked = BOOKED.get((restaurant_name, date, time), 0)
    remaining = max_seats - booked

    if remaining <= 0:
        return (
            f"❌ 예약 실패\n"
            f"식당: {restaurant_name}\n"
            f"사유: 해당 시간대 만석입니다."
        )

    if party_size > remaining:
        return (
            f"❌ 예약 실패\n"
            f"식당: {restaurant_name}\n"
            f"사유: 남은 좌석({remaining}석)이 요청 인원({party_size}명)보다 적습니다."
        )

    # 예약 확정
    reservation_id = f"RSV-{len(RESERVATIONS) + 1:04d}"
    reservation = {
        "id": reservation_id,
        "restaurant": restaurant_name,
        "date": date,
        "time": time,
        "party_size": party_size,
        "customer": customer_name,
    }
    RESERVATIONS.append(reservation)

    # 좌석 차감
    key = (restaurant_name, date, time)
    BOOKED[key] = booked + party_size

    return (
        f"✅ 예약 확정\n"
        f"예약 번호: {reservation_id}\n"
        f"식당: {restaurant_name}\n"
        f"날짜: {date} {time}\n"
        f"인원: {party_size}명\n"
        f"예약자: {customer_name}\n"
        f"남은 좌석: {remaining - party_size}석"
    )


# ── 도구 3: 비용 산정 ─────────────────────────────────
@mcp.tool()
def estimate_cost(
    restaurant_name: str,
    party_size: int,
    menu_items: list[str] | None = None,
    budget_per_person: int | None = None,
) -> str:
    """식사 비용을 산정합니다.

    메뉴를 지정하면 해당 메뉴 기준으로, 지정하지 않으면 평균 객단가로 산정합니다.
    1인 예산을 지정하면 예산 내 추천 메뉴 조합을 제안합니다.

    Args:
        restaurant_name: 식당 이름
        party_size: 인원 수
        menu_items: 주문할 메뉴 리스트 (선택). None이면 평균 객단가로 산정.
        budget_per_person: 1인 예산 (선택, 원 단위). None이면 예산 제한 없음.

    Returns:
        비용 산정 결과 (메뉴별 가격, 총액, 서비스 차지, 1인당 금액)
    """
    if restaurant_name not in MENU_PRICES:
        return f"'{restaurant_name}' 식당의 메뉴 정보가 없습니다."

    prices = MENU_PRICES[restaurant_name]
    service_rate = SERVICE_CHARGE.get(restaurant_name, 0.0)

    # 메뉴 지정된 경우
    if menu_items:
        total = 0
        breakdown = []
        not_found = []

        for item in menu_items:
            if item in prices:
                price = prices[item]
                breakdown.append(f"  - {item}: {price:,}원")
                total += price
            else:
                not_found.append(item)

        if not_found:
            available_menus = ", ".join(prices.keys())
            return (
                f"다음 메뉴를 찾을 수 없습니다: {', '.join(not_found)}\n"
                f"사용 가능한 메뉴: {available_menus}"
            )

        subtotal = total * party_size
        service_charge = int(subtotal * service_rate)
        grand_total = subtotal + service_charge
        per_person = grand_total // party_size

        result = (
            f"💰 비용 산정 — {restaurant_name}\n"
            f"인원: {party_size}명\n\n"
            f"📋 주문 메뉴 (1인 기준):\n"
            + "\n".join(breakdown) + "\n"
            f"\n소계 (1인): {total:,}원\n"
            f"소계 ({party_size}명): {subtotal:,}원\n"
        )
        if service_rate > 0:
            result += f"서비스 차지 ({int(service_rate*100)}%): {service_charge:,}원\n"
        result += (
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"총 합계: {grand_total:,}원\n"
            f"1인당: {per_person:,}원"
        )
        return result

    # 메뉴 미지정 — 평균 객단가 기반 산정
    avg_price = sum(prices.values()) // len(prices)
    subtotal = avg_price * party_size
    service_charge = int(subtotal * service_rate)
    grand_total = subtotal + service_charge
    per_person = grand_total // party_size

    budget_info = ""
    if budget_per_person:
        affordable = [f"  - {name}: {p:,}원" for name, p in prices.items() if p <= budget_per_person]
        over_budget = [f"  - {name}: {p:,}원 ⚠️" for name, p in prices.items() if p > budget_per_person]
        budget_info = (
            f"\n📊 1인 예산 {budget_per_person:,}원 기준:\n"
            f"✅ 예산 내 메뉴:\n" + "\n".join(affordable) + "\n"
        )
        if over_budget:
            budget_info += f"❌ 예산 초과:\n" + "\n".join(over_budget) + "\n"

    result = (
        f"💰 비용 산정 — {restaurant_name}\n"
        f"인원: {party_size}명\n"
        f"평균 객단가: {avg_price:,}원\n\n"
        f"예상 총액: {subtotal:,}원\n"
    )
    if service_rate > 0:
        result += f"서비스 차지 ({int(service_rate*100)}%): {service_charge:,}원\n"
    result += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"합계: {grand_total:,}원\n"
        f"1인당: {per_person:,}원"
    )
    result += budget_info

    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
