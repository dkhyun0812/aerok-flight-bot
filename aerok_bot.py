import asyncio
import time
import requests
from playwright.async_api import async_playwright

TELEGRAM_TOKEN = "8682540599:AAGZfAN2sVuLIjs_mmnzeV3mUFTe8YXBqGg"
CHAT_ID = "108147841"

ORIGIN = "CJJ"
DESTINATION = "KKJ"
TARGET_DATE = "2027-02-04"
CHECK_INTERVAL = 300


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
            print(f"[오류] 발송 실패: {response.text}")
    except Exception as e:
        print(f"[오류] 네트워크 예외: {e}")


async def check_trip_com(page, date_str):
    try:
        url = f"https://kr.trip.com/flights/cheongju-to-kitakyushu/one-way-cjj-kkj?dby={date_str}&quantity=1&class=y"
        print("  [트립닷컴] 페이지 접속 중...")
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(8)
        content = await page.content()
        has_flight = "에어로케이" in content or "Aero K" in content or "RF" in content
        no_seats = "결과가 없습니다" in content or "항공편을 찾을 수 없습니다" in content or "모두 매진" in content
        if has_flight and not no_seats:
            return True, url
        return False, url
    except Exception as e:
        print(f"  [오류] 트립닷컴 실패: {e}")
        return None, None


async def check_naver_flights(page, date_str_compact):
    try:
        url = f"https://flight.naver.com/flights/international/CJJ-KKJ-{date_str_compact}?adult=1&isDirect=true"
        print("  [네이버 항공권] 페이지 접속 중...")
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(9)
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(2)
        content = await page.content()
        has_flight = "에어로케이" in content or "Aero K" in content or "RF" in content
        no_seats = "조건에 맞는 항공권이 없습니다" in content or "결과가 없습니다" in content or "매진" in content
        if has_flight and not no_seats:
            return True, url
        return False, url
    except Exception as e:
        print(f"  [오류] 네이버 실패: {e}")
        return None, None


async def run_scan():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"[{timestamp}] 항공권 검증 시작 (대상: {TARGET_DATE})")

            trip_found, trip_url = await check_trip_com(page, TARGET_DATE)
            if trip_found:
                print(f"[{timestamp}] [트립닷컴] 에어로케이 좌석 감지!")
                msg = f"✈️ *[에어로케이] 취소표 발생 (트립닷컴)*\n\n• 노선: 청주➔기타규슈\n• 날짜: {TARGET_DATE}\n• 링크: {trip_url}"
                send_telegram_message(msg)
                return True

            naver_date = TARGET_DATE.replace("-", "")
            naver_found, naver_url = await check_naver_flights(page, naver_date)
            if naver_found:
                print(f"[{timestamp}] [네이버] 에어로케이 좌석 감지!")
                msg = f"✈️ *[에어로케이] 취소표 발생 (네이버)*\n\n• 노선: 청주➔기타규슈\n• 날짜: {TARGET_DATE}\n• 링크: {naver_url}"
                send_telegram_message(msg)
                return True

            print(f"[{timestamp}] 여전히 매진 상태입니다.")
            return False
        except Exception as e:
            print(f"[오류] 검증 예외: {e}")
            return False
        finally:
            await browser.close()


async def main():
    welcome_msg = f"🤖 에어로케이 통합 감지 봇 시작\n• 대상: {TARGET_DATE} 청주➔기타규슈\n• 주기: {CHECK_INTERVAL // 60}분 마다"
    send_telegram_message(welcome_msg)
    while True:
        found = await run_scan()
        if found:
            await asyncio.sleep(600)
        else:
            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())