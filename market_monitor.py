import os
import json
import datetime
import pytz
import yfinance as yf
import google.generativeai as genai
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# 1. 설정
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("Warning: GEMINI_API_KEY not found. AI summary will be skipped.")
    API_KEY = "DUMMY" 

if API_KEY != "DUMMY":
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-pro')

# 2. 시간대 판단 함수
def is_overnight_session():
    """현재가 야간 세션(18:00 ~ 09:00 KST)인지 확인"""
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(seoul_tz)
    current_hour = now.hour
    # 18:00 ~ 23:59 또는 00:00 ~ 08:59
    return current_hour >= 18 or current_hour < 9

# 3. 데이터 수집 (Yahoo Finance)
def fetch_market_data():
    tickers = {
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "KOSPI": "^KS11",
        "USD/KRW": "KRW=X",
        "Bitcoin": "BTC-USD"
    }
    
    data_summary = []
    
    for name, symbol in tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="2d")
            
            if len(hist) >= 2:
                close_today = hist['Close'].iloc[-1]
                close_prev = hist['Close'].iloc[-2]
                change = close_today - close_prev
                change_pct = (change / close_prev) * 100
                
                data_summary.append(f"{name}: {close_today:,.2f} ({change_pct:+.2f}%)")
            else:
                if len(hist) == 1:
                    close_today = hist['Close'].iloc[-1]
                    data_summary.append(f"{name}: {close_today:,.2f} (변동폭 계산 불가)")
                else:
                    data_summary.append(f"{name}: 데이터 부족")
        except Exception as e:
            data_summary.append(f"{name}: 가져오기 실패 ({str(e)})")
            
    return "\n".join(data_summary)

# 4. 데이터 수집 (CNN Fear & Greed)
def fetch_fear_and_greed():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://edition.cnn.com/markets/fear-and-greed", timeout=60000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            score_el = soup.find(class_="market-fng-gauge__dial-number-value")
            rating_el = soup.find(class_="market-fng-gauge__label")
            
            if score_el and rating_el:
                return f"CNN Fear & Greed: {score_el.get_text().strip()} ({rating_el.get_text().strip()})"
            
            text = soup.get_text()
            if "Fear & Greed Index" in text:
                return "CNN Fear & Greed: 페이지 접근 성공 (값 추출 실패)"
            
            return "CNN Fear & Greed: 데이터 추출 실패"
            
    except Exception as e:
        return f"CNN Fear & Greed: 수집 오류 ({str(e)})"

# 5. 데이터 수집 (Telegram - 야간 전용)
def fetch_telegram_updates():
    channels = {
        "Kiwoom US (@kwusa)": "https://t.me/s/kwusa",
        "WatcherGuru (@WatcherGuru)": "https://t.me/s/WatcherGuru"
    }
    
    updates = []
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            for name, url in channels.items():
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=30000)
                    page.wait_for_selector(".tgme_widget_message", timeout=5000)
                    
                    content = page.content()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    # Get last 3 messages
                    messages = soup.select(".tgme_widget_message_text")
                    recent_msgs = []
                    for msg in messages[-3:]:
                        text = msg.get_text(strip=True)
                        if len(text) > 20:
                            recent_msgs.append(text[:200] + "..." if len(text) > 200 else text)
                    
                    if recent_msgs:
                        updates.append(f"[{name}]\n" + "\n---\n".join(recent_msgs))
                    else:
                        updates.append(f"[{name}] 최근 메시지 없음")
                        
                    page.close()
                except Exception as e:
                    updates.append(f"[{name}] 수집 실패: {str(e)}")
            
            browser.close()
            
    except Exception as e:
        return f"텔레그램 수집 중 오류: {str(e)}"
        
    return "\n\n".join(updates)

# 6. 데이터 수집 (Kiwoom - 주간 전용)
def fetch_kiwoom_report():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            
            url = "https://www1.kiwoom.com/h/invest/research/VAnalUDView?dummyVal=0"
            page.goto(url, timeout=60000)
            page.wait_for_timeout(5000)
            
            content = page.content()
            browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            board_text = ""
            tables = soup.find_all('table')
            for table in tables:
                if "작성일" in table.get_text():
                    rows = table.find_all('tr')
                    for row in rows[:4]:
                        board_text += row.get_text(strip=True) + "\n"
                    break
            
            if board_text:
                return f"키움증권 리서치 목록:\n{board_text}"
            else:
                return "키움증권 리서치: 목록을 찾을 수 없음"

    except Exception as e:
        return f"키움증권 리서치: 수집 오류 ({str(e)})"

# 7. AI 요약 (시간대별 프롬프트 분기)
def generate_briefing(market_data, cnn_data, telegram_data=None, kiwoom_data=None):
    if API_KEY == "DUMMY":
        return "API 키가 설정되지 않아 AI 요약을 생성할 수 없습니다."

    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(seoul_tz)
    current_hour = now.hour
    
    # 야간 세션 (18:00 ~ 09:00)
    if is_overnight_session():
        prompt = f"""
        당신은 24시간 시장을 모니터링하는 AI 에이전트입니다. 
        현재 시각은 **{now.strftime('%H:%M')} (한국시간)** 입니다.
        밤 시간대이므로 미국 증시 및 글로벌 시장의 실시간 동향에 집중해주세요.
        
        [시장 지표]
        {market_data}
        
        [투자 심리]
        {cnn_data}
        
        [텔레그램 실시간 속보]
        {telegram_data if telegram_data else "데이터 없음"}
        
        [요청 사항]
        1. 한국어(존댓말)로 작성하세요.
        2. 현재 시각에 맞는 인사말을 건네세요 (예: "좋은 저녁입니다", "밤 사이 시장은...").
        3. 텔레그램 속보 중 중요한 내용을 우선 언급하세요.
        4. CNN 공포/탐욕 지수의 의미를 언급하세요.
        5. 전체 길이는 400자 내외로 작성하세요.
        """
    # 주간 세션 (09:00 ~ 18:00)
    else:
        prompt = f"""
        당신은 한국 증권 시장 전문 애널리스트입니다.
        현재 시각은 **{now.strftime('%H:%M')} (한국시간)** 입니다.
        주간 시간대이므로 한국 증권사의 시황 분석 및 종합 시장 상황을 정리해주세요.
        
        [시장 지표]
        {market_data}
        
        [투자 심리]
        {cnn_data}
        
        [키움증권 미국 시황 리포트]
        {kiwoom_data if kiwoom_data else "데이터 없음"}
        
        [요청 사항]
        1. 한국어(존댓말)로 작성하세요.
        2. 오늘의 시장 분위기를 한 문장으로 요약하는 제목을 붙이세요.
        3. 키움증권 리포트의 핵심 내용을 언급하세요.
        4. 투자자들에게 주는 짧은 조언으로 마무리하세요.
        5. 전체 길이는 400자 내외로 작성하세요.
        """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류 발생: {str(e)}"

# 8. 실행 및 저장
def main():
    print("=== 시장 모니터 시작 ===")
    
    # 시간대 확인
    is_night = is_overnight_session()
    session_type = "야간 세션 (실시간 모니터링)" if is_night else "주간 세션 (시황 정리)"
    print(f"현재 세션: {session_type}\n")
    
    print("1. 시장 데이터 수집 중...")
    market_data = fetch_market_data()
    
    print("2. CNN 공포/탐욕 지수 수집 중...")
    cnn_data = fetch_fear_and_greed()
    
    telegram_data = None
    kiwoom_data = None
    
    if is_night:
        print("3. [야간] 텔레그램 속보 수집 중...")
        telegram_data = fetch_telegram_updates()
    else:
        print("3. [주간] 키움증권 리포트 수집 중...")
        kiwoom_data = fetch_kiwoom_report()
    
    print(f"\n[수집 결과]\n{market_data}\n{cnn_data}\n")
    
    print("4. AI 분석 및 요약 중...")
    briefing_text = generate_briefing(market_data, cnn_data, telegram_data, kiwoom_data)
    
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(seoul_tz)
    date_str = now.strftime("%Y년 %m월 %d일 %H:%M")
    
    output = {
        "date": date_str,
        "session_type": session_type,
        "market_data": market_data,
        "cnn_data": cnn_data,
        "telegram_data": telegram_data if is_night else None,
        "kiwoom_data": kiwoom_data if not is_night else None,
        "briefing": briefing_text
    }
    
    os.makedirs("data", exist_ok=True)
    
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print("data/briefing.json 저장 완료")
    print(f"세션 타입: {session_type}")

if __name__ == "__main__":
    main()
