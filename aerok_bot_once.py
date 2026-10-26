import os
import asyncio
import time
import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

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
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"[오류] 텔레그램 발송 실패: {res.text}")
    except Exception as e:
        print(f"[오류] 네트워크 예외: {e}")

async def check_naver_flights(page, target):
    origin, destination, date_str = target["origin"], target["destination"], target["date"]
    date_compact = date_str.replace("-", "")
    keywords, max_price = target["airline_keywords"], target.get("max_price")

    url = f"https://flight.naver.com/flights/international/{origin}-{destination}-{date_compact}?adult=1&isDirect=true"
    print(f"  [{target['name']} ({date_str}) | {target['airline']}] 접속 중...")

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await asyncio.sleep(12)
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(2)

        payload = {"kwList": keywords, "maxPrice": max_price}
        result = await page.evaluate(r"""(args) => {
            const rawText = document.body.innerText || "";
            const noFlight = rawText.includes("조건에 맞는 항공권이 없습니다") || 
                             rawText.includes("결과가 없습니다") || 
                             rawText.includes("항공편을 찾을 수 없습니다");
            if (noFlight) return { isAvailable: false, minPrice: null };

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
                    if (args.kwList.some(kw => text.includes(kw.toLowerCase()))) {
                        foundTargetAirline = true;
                        let card = el;
                        while (card && card !== document.body) {
                            const cardText = card.innerText || "";
                            if (cardText.includes("원")) {
                                if (!competingAirlines.some(ca => cardText.toLowerCase().includes(ca))) {
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
                                } else break;
                            }
                            card = card.parentElement;
                        }
                    }
                }
            }

            let priceMatch = targetAirlineMinPrice !== null ? (args.maxPrice ? targetAirlineMinPrice <= args.maxPrice : true) : false;
            return { isAvailable: (foundTargetAirline && priceMatch), minPrice: targetAirlineMinPrice };
        }""", payload)

        return result["isAvailable"], url, result.get("minPrice")
    except Exception as e:
        print(f"  └ [오류] {target['name']} 예외: {e}")
        return False, None, None

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            locale="ko-KR", timezone_id="Asia/Seoul"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] 🔎 GitHub Actions 1회 자동 스캔 시작")

        # 1. 깃허브 실행 시 텔레그램 시작 알림 전송
        start_msg = f"🤖 *[GitHub Actions]* 항공권 자동 모니터링 스캔을 시작합니다.\n• 실행 시각: {timestamp}"
        send_telegram_message(start_msg)

        # 2. 노선별 스캔 진행 및 상세 로그 출력
        for target in TARGETS:
            found, naver_url, price = await check_naver_flights(page, target)
            price_text = f"{price:,}원" if price else "미감지"

            if found:
                max_price_text = f" ({target['max_price']:,}원 이하 조건 충족)" if target.get('max_price') else ""
                print(f"  └ 🎉 [조건 충족] {target['name']} [{target['airline']}]: {price_text} 감지 및 특가 알림 발송")
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