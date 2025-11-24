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
    # 로컬 테스트를 위한 예외 처리 (실제 배포 시에는 환경 변수 필수)
    print("Warning: GEMINI_API_KEY not found. AI summary will be skipped.")
    API_KEY = "DUMMY" 

if API_KEY != "DUMMY":
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel('gemini-pro')

# 2. 데이터 수집 (Yahoo Finance)
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
                # 장 중이거나 데이터가 하나뿐일 때
                if len(hist) == 1:
                    close_today = hist['Close'].iloc[-1]
                    data_summary.append(f"{name}: {close_today:,.2f} (변동폭 계산 불가)")
                else:
                    data_summary.append(f"{name}: 데이터 부족")
        except Exception as e:
            data_summary.append(f"{name}: 가져오기 실패 ({str(e)})")
            
    return "\n".join(data_summary)

# 3. 데이터 수집 (CNN Fear & Greed)
def fetch_fear_and_greed():
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto("https://www.cnn.com/markets/fear-and-greed", timeout=60000)
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
                return "CNN Fear & Greed: 데이터 페이지 접근 성공 (상세 값 추출 실패)"
            
            return "CNN Fear & Greed: 데이터 추출 실패"
            
    except Exception as e:
        return f"CNN Fear & Greed: 수집 오류 ({str(e)})"

# 4. 데이터 수집 (Telegram)
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
                    for msg in messages[-3:]: # Last 3
                        text = msg.get_text(strip=True)
                        if len(text) > 20: # Filter short/empty
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
        return f"텔레그램 수집 중 치명적 오류: {str(e)}"
        
    return "\n\n".join(updates)

# 5. AI 요약
def generate_briefing(market_data, cnn_data, telegram_data):
    if API_KEY == "DUMMY":
        return "API 키가 설정되지 않아 AI 요약을 생성할 수 없습니다."

    prompt = f"""
    당신은 24시간 시장을 모니터링하는 AI 에이전트입니다. 
    현재 시각(한국 시간 기준)에 맞춰 최신 시장 상황을 브리핑해주세요.
    
    [시장 지표]
    {market_data}
    
    [투자 심리]
    {cnn_data}
    
    [실시간 텔레그램 속보 (최근 1시간)]
    {telegram_data}
    
    [요청 사항]
    1. 한국어(존댓말)로 작성하세요.
    2. **현재 시각**을 고려하여 인사말을 건네세요 (예: "좋은 저녁입니다", "밤 사이 시장은...").
    3. 텔레그램 속보 중 중요한 내용이 있다면 우선적으로 언급하세요.
    4. 별다른 속보가 없다면 시장 지표 위주로 정리하세요.
    5. 전체 길이는 400자 내외로 작성하세요.
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류 발생: {str(e)}"

# 6. 실행 및 저장
def main():
    print("1. 시장 데이터 수집 중...")
    market_data = fetch_market_data()
    
    print("2. CNN 공포/탐욕 지수 수집 중...")
    cnn_data = fetch_fear_and_greed()
    
    print("3. 텔레그램 속보 수집 중...")
    telegram_data = fetch_telegram_updates()
    
    print(f"\n[수집 결과 요약]\n{market_data}\n{cnn_data}\n(텔레그램 데이터 생략)\n")
    
    print("4. AI 분석 및 요약 중...")
    briefing_text = generate_briefing(market_data, cnn_data, telegram_data)
    
    # 한국 시간 구하기
    seoul_tz = pytz.timezone('Asia/Seoul')
    now = datetime.datetime.now(seoul_tz)
    date_str = now.strftime("%Y년 %m월 %d일 %H:%M")
    
    output = {
        "date": date_str,
        "market_data": market_data,
        "cnn_data": cnn_data,
        "telegram_data": telegram_data,
        "briefing": briefing_text
    }
    
    # data 폴더가 없으면 생성
    os.makedirs("data", exist_ok=True)
    
    with open("data/briefing.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print("data/briefing.json 저장 완료")

if __name__ == "__main__":
    main()
