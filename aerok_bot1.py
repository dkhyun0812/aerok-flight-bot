import asyncio
import time
import requests
from playwright.async_api import async_playwright

# ==========================================
# [설정 정보 입력]
# ==========================================
TELEGRAM_TOKEN = "8682540599:AAGZfAN2sVuLIjs_mmnzeV3mUFTe8YXBqGg" # 본인의 봇 토큰 (예: "123456789:ABC...")
CHAT_ID = "108147841"         # 본인의 Chat ID (예: "123456789")

ORIGIN = "CJJ"          # 청주 (CJJ)
DESTINATION = "KKJ"     # 기타규슈 (KKJ)
TARGET_DATE = "2027-02-06"  # 원하는 날짜 YYYY-MM-DD (검증 시 "2027-02-04")
CHECK_INTERVAL = 300     # 확인 주기 (300초 = 5분)


def send_telegram_message(message: str):
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


async def check_naver_flights(page, date_str_compact):
    try:
        url = f"https://flight.naver.com/flights/international/CJJ-KKJ-{date_str_compact}?adult=1&isDirect=true"
        print("  [네이버 항공권] 페이지 접속 중...")
        
        # 1. 네이버 항공권 접속
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        
        # 2. 동적 로딩 대기 (10초)
        print("  [네이버 항공권] 검색 결과 로딩 대기 중...")
        await asyncio.sleep(10)

        # 스크롤하여 모든 항공편 데이터 확정 렌더링
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(2)

        # 3. raw string(r""")과 [0-9]를 사용하여 문법 이스케이프 오류 완전 차단
        result = await page.evaluate(r"""() => {
            const text = document.body.innerText || "";
            
            // 매진 / 결과 없음 문구
            const noFlight = text.includes("조건에 맞는 항공권이 없습니다") || 
                             text.includes("결과가 없습니다") || 
                             text.includes("항공편을 찾을 수 없습니다");
            
            // 에어로케이 키워드
            const hasAerok = text.includes("에어로케이") || text.includes("Aero K") || text.includes("RF");
            
            // 가격 패턴 (숫자와 '원' 조합 감지)
            const priceMatch = text.includes("원") && /[0-9]{3,}/.test(text);

            return {
                noFlight: noFlight,
                hasAerok: hasAerok,
                priceMatch: priceMatch,
                isAvailable: (!noFlight && hasAerok && priceMatch)
            };
        }""")
        
        if result["isAvailable"]:
            return True, url
        else:
            print(f"  [진단] 매진판단 이유 -> 결과없음문구:{result['noFlight']}, 에어로케이키워드:{result['hasAerok']}, 가격표시:{result['priceMatch']}")
            return False, url

    except Exception as e:
        print(f"  [오류] 네이버 조회 예외 발생: {e}")
        return None, None


async def run_scan():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False) 
        context = await browser.new_context(
            viewport={"width": 1280, "height": 850},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] 🔎 항공권 실시간 스캔 중 (대상일: {TARGET_DATE})")

            naver_date = TARGET_DATE.replace("-", "")
            found, naver_url = await check_naver_flights(page, naver_date)
            
            if found:
                print(f"[{timestamp}] 🎉 에어로케이 좌석 감지! (예약 가능)")
                msg = f"""✈️ *[에어로케이] 취소표/좌석 발생 알림*

• **노선**: 청주({ORIGIN}) ➔ 기타규슈({DESTINATION})
• **날짜**: {TARGET_DATE}
• **상태**: 예약 가능한 좌석이 감지되었습니다!
• **네이버 항공권 링크**: {naver_url}"""
                send_telegram_message(msg)
                return True

            print(f"[{timestamp}] ❌ 조회 결과: 매진 상태입니다.")
            return False

        except Exception as e:
            print(f"[오류] 검증 예외: {e}")
            return False
        finally:
            await browser.close()


async def main():
    welcome_msg = f"""🤖 *에어로케이 감지 봇 가동*
• 대상: {TARGET_DATE} 청주 ➔ 기타규슈
• 검사 주기: {CHECK_INTERVAL // 60}분 마다"""
    send_telegram_message(welcome_msg)
    
    while True:
        found = await run_scan()
        if found:
            await asyncio.sleep(600) # 연속 알림 방지 (10분 대기)
        else:
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())