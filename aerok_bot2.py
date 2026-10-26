import asyncio
import time
import requests
from playwright.async_api import async_playwright

# ==========================================
# [설정 정보 입력]
# ==========================================
TELEGRAM_TOKEN = "8682540599:AAGZfAN2sVuLIjs_mmnzeV3mUFTe8YXBqGg"  # 본인의 봇 토큰
CHAT_ID = "108147841"          # 본인의 Chat ID
CHECK_INTERVAL = 180                      # 확인 주기 (300초 = 5분)

# 모니터링 대상 항공권 리스트
TARGETS = [
    {
        "name": "후쿠오카 ➔ 청주",
        "origin": "FUK",
        "destination": "CJJ",
        "date": "2027-02-09", # 9일
        "airline": "트리니티 항공",
        "airline_keywords": ["트리니티", "trinity"],
        "max_price": 400000  # 40만 원 이하일 때만 알림
    },
    {
        "name": "청주 ➔ 기타규슈",
        "origin": "CJJ",
        "destination": "KKJ",
        "date": "2027-02-06", # 6일
        "airline": "에어로케이 항공",
        "airline_keywords": ["에어로", "aerok", "aero k", "rf"],
        "max_price": None    # 가격 제한 없음
    }
]


def send_telegram_message(message: str):
    """텔레그램 메시지 발송"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"[오류] 텔레그램 발송 실패: {response.text}")
    except Exception as e:
        print(f"[오류] 네트워크 예외: {e}")


async def check_naver_flights(page, target):
    """타 항공사 가격 혼입 방지 정밀 매칭"""
    origin = target["origin"]
    destination = target["destination"]
    date_str = target["date"]
    date_compact = date_str.replace("-", "")
    name = target["name"]
    airline_name = target["airline"]
    keywords = target["airline_keywords"]
    max_price = target.get("max_price")

    url = f"https://flight.naver.com/flights/international/{origin}-{destination}-{date_compact}?adult=1&isDirect=true"
    print(f"  [{name} ({date_str}) | {airline_name}] 접속 중...")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await asyncio.sleep(10)  # 동적 데이터 로딩 대기

        # 스크롤하여 결과 확정 렌더링
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(2)

        payload = {"kwList": keywords, "maxPrice": max_price}
        result = await page.evaluate(r"""(args) => {
            const rawText = document.body.innerText || "";
            
            const noFlight = rawText.includes("조건에 맞는 항공권이 없습니다") || 
                             rawText.includes("결과가 없습니다") || 
                             rawText.includes("항공편을 찾을 수 없습니다");
            
            if (noFlight) {
                return { noFlight: true, hasAirline: false, priceMatch: false, minPrice: null, isAvailable: false };
            }

            // 혼입 방지용 경쟁 항공사 목록
            const knownAirlines = ["에어로", "aerok", "트리니티", "trinity", "대한항공", "아시아나", "제주항공", "진에어", "티웨이", "에어부산", "에어서울", "이스타"];
            
            // 현재 찾고자 하는 항공사 키워드를 제외한 경쟁 항공사 키워드 필터링
            const competingAirlines = knownAirlines.filter(a => 
                !args.kwList.some(kw => kw.toLowerCase().includes(a) || a.includes(kw.toLowerCase()))
            );

            const allElements = Array.from(document.querySelectorAll('*'));
            let foundTargetAirline = false;
            let targetAirlineMinPrice = null;

            for (let el of allElements) {
                if (el.children.length <= 3) {
                    const text = (el.innerText || el.textContent || "").toLowerCase();
                    const matchedKw = args.kwList.some(kw => text.includes(kw.toLowerCase()));

                    if (matchedKw) {
                        foundTargetAirline = true;

                        // 부모 요소로 거슬러 올라가며 단일 카드 영역 탐색
                        let card = el;
                        while (card && card !== document.body) {
                            const cardText = card.innerText || "";
                            const lowerCardText = cardText.toLowerCase();

                            // 1. 가격 표기("원")가 있는지 확인
                            if (cardText.includes("원")) {
                                // 2. 다른 경쟁 항공사 이름이 섞여 들어왔는지 검사 (부모 영역 과다 침범 방지)
                                const hasConflict = competingAirlines.some(ca => lowerCardText.includes(ca));

                                if (!hasConflict) {
                                    // 순수 단일 항공권 카드인 경우에만 가격 추출
                                    const priceRegex = /([0-9,]+)\s*원/g;
                                    let match;
                                    while ((match = priceRegex.exec(cardText)) !== null) {
                                        const num = parseInt(match[1].replace(/,/g, ''), 10);
                                        if (!isNaN(num) && num > 10000) {
                                            if (targetAirlineMinPrice === null || num < targetAirlineMinPrice) {
                                                targetAirlineMinPrice = num;
                                            }
                                        }
                                    }
                                    if (targetAirlineMinPrice !== null) break; // 해당 카드의 가격 확보 완료
                                } else {
                                    // 타 항공사가 섞인 상위 상자로 올라갔으므로 더 이상의 상위 추적 중단
                                    break;
                                }
                            }
                            card = card.parentElement;
                        }
                    }
                }
            }

            let priceMatch = false;
            if (targetAirlineMinPrice !== null) {
                if (args.maxPrice) {
                    priceMatch = targetAirlineMinPrice <= args.maxPrice;
                } else {
                    priceMatch = true;
                }
            }

            return {
                noFlight: false,
                hasAirline: foundTargetAirline,
                priceMatch: priceMatch,
                minPrice: targetAirlineMinPrice,
                isAvailable: (foundTargetAirline && priceMatch)
            };
        }""", payload)

        if result["isAvailable"]:
            return True, url, result["minPrice"]
        else:
            price_str = f"{result['minPrice']:,}원" if result['minPrice'] else "미감지"
            limit_str = f" ({max_price:,}원 이하 조건)" if max_price else ""
            print(f"  └ [상태] 매진/조건미달 (결과없음:{result['noFlight']}, 항공사({airline_name}):{result['hasAirline']}, 해당항공사 가격:{price_str}{limit_str})")
            return False, url, result["minPrice"]

    except Exception as e:
        print(f"  └ [오류] {name} 조회 중 예외 발생: {e}")
        return None, None, None


async def run_scan():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=Falase)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n[{timestamp}] 🔎 정밀 카드 스캔 시작")

            found_any = False

            for target in TARGETS:
                found, naver_url, price = await check_naver_flights(page, target)
                if found:
                    found_any = True
                    price_text = f"{price:,}원" if price else "확인 필요"
                    max_price_text = f" ({target['max_price']:,}원 이하 조건 충족)" if target.get('max_price') else ""
                    
                    print(f"[{timestamp}] 🎉 {target['name']} [{target['airline']}] {price_text} 감지!")
                    msg = f"""✈️ *[특가/취소표 발생 알림]*

• **노선**: {target['name']} ({target['origin']} ➔ {target['destination']})
• **날짜**: {target['date']}
• **항공사**: {target['airline']}
• **최저가**: *{price_text}*{max_price_text}
• **네이버 항공권 링크**: {naver_url}"""
                    send_telegram_message(msg)
                else:
                    print(f"[{timestamp}] ❌ {target['name']} [{target['airline']}]: 조건 만족 좌석 없음")

            return found_any

        except Exception as e:
            print(f"[오류] 스캔 프로세스 예외: {e}")
            return False
        finally:
            await browser.close()


async def main():
    targets_info = []
    for t in TARGETS:
        price_cond = f" [{t['max_price']:,}원 이하]" if t.get('max_price') else ""
        targets_info.append(f"• {t['date']}: {t['name']} ({t['airline']}){price_cond}")
    
    welcome_msg = f"""🤖 *혼입 방지 정밀 감지 봇 가동*
{chr(10).join(targets_info)}
• 검사 주기: {CHECK_INTERVAL // 60}분 마다"""
    send_telegram_message(welcome_msg)

    while True:
        found = await run_scan()
        if found:
            await asyncio.sleep(CHECK_INTERVAL)  # 알림 발송 후 10분 대기
        else:
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())