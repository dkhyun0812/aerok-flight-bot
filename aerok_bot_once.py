import os
import asyncio
import time
import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

# GitHub Secrets 및 로컬 .env 모두 대응
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

TARGETS = [
    {
        "name": "후쿠오카 ➔ 청주",
        "origin": "FUK",
        "destination": "CJJ",
        "date": "2027-02-04",
        "airline": "트리니티 항공",
        "airline_keywords": ["트리니티", "trinity"],
        "max_price": 400000
    },
    {
        "name": "청주 ➔ 기타규슈",
        "origin": "CJJ",
        "destination": "KKJ",
        "date": "2027-02-06",
        "airline": "에어로케이 항공",
        "airline_keywords": ["에어로", "aerok", "aero k", "rf"],
        "max_price": None
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
    """검증된 항공사 및 가격 추출 로직"""
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
        await asyncio.sleep(12)  # 동적 항공권 데이터 로딩 대기

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

            const knownAirlines = ["에어로", "aerok", "트리니티", "trinity", "대한항공", "아시아나", "제주항공", "진에어", "티웨이", "에어부산", "에어서울", "이스타"];
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

                        let card = el;
                        while (card && card !== document.body) {
                            const cardText = card.innerText || "";
                            const lowerCardText = cardText.toLowerCase();

                            if (cardText.includes("원")) {
                                const hasConflict = competingAirlines.some(ca => lowerCardText.includes(ca));

                                if (!hasConflict) {
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
                                    if (targetAirlineMinPrice !== null) break;
                                } else {
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
            return False, url, result["minPrice"]

    except Exception as e:
        print(f"  └ [오류] {name} 조회 중 예외 발생: {e}")
        return False, None, None

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ko-KR",
            timezone_id="Asia/Seoul"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] 🔎 GitHub Actions 1회 자동 스캔 시작")

        # 스캔 시작 텔레그램 알림
        start_msg = f"🤖 *[GitHub Actions]* 항공권 스캔을 진행합니다.\n• 실행 시각: {timestamp}"
        send_telegram_message(start_msg)

        for target in TARGETS:
            found, naver_url, price = await check_naver_flights(page, target)
            price_text = f"{price:,}원" if price else "미감지"

            if found:
                max_price_text = f" ({target['max_price']:,}원 이하 조건 충족)" if target.get('max_price') else ""
                print(f"  └ 🎉 [좌석 감지] {target['name']} [{target['airline']}]: {price_text} 감지 완료")
                
                msg = f"""✈️ *[GitHub Actions 감지 알림]*

• **노선**: {target['name']} ({target['origin']} ➔ {target['destination']})
• **날짜**: {target['date']}
• **항공사**: {target['airline']}
• **최저가**: *{price_text}*{max_price_text}
• **네이버 항공권 링크**: {naver_url}"""
                send_telegram_message(msg)
            else:
                limit_text = f" ({target['max_price']:,}원 이하 조건)" if target.get('max_price') else ""
                print(f"  └ ❌ [조건 미충족/매진] {target['name']} [{target['airline']}]: 현재 최저가 {price_text}{limit_text}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())