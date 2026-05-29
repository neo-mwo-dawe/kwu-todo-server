"""
debug_klas.py
KLAS 로그인 후 실제 페이지 구조 확인용 디버그 스크립트
"""
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time

STUDENT_ID = input("학번 입력: ")
PASSWORD   = input("비밀번호 입력: ")

options = Options()
# 헤드리스 끄고 실제 창 띄워서 확인
# options.add_argument("--headless")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

driver = webdriver.Chrome(options=options)
wait   = WebDriverWait(driver, 15)

try:
    # 1. 로그인
    driver.get("https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do")
    wait.until(EC.presence_of_element_located((By.ID, "loginId")))
    driver.find_element(By.ID, "loginId").send_keys(STUDENT_ID)
    driver.find_element(By.ID, "loginPwd").send_keys(PASSWORD)

    # 로그인 버튼 찾기
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    except:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".btn-login")
        except:
            btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
    btn.click()

    time.sleep(3)
    print("현재 URL:", driver.current_url)

    # 2. 대시보드 HTML 저장
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("dashboard.html 저장 완료!")

    # 3. 과제 관련 텍스트 찾기
    soup = BeautifulSoup(driver.page_source, "html.parser")
    print("\n=== 과제/퀴즈 관련 텍스트 (상위 20개) ===")
    count = 0
    for el in soup.find_all(text=True):
        text = el.strip()
        if any(k in text for k in ["과제", "퀴즈", "마감", "제출", "강의"]):
            if len(text) > 3 and count < 20:
                print(f"  [{el.parent.name}] {text[:80]}")
                count += 1

    # 4. iframe 확인
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    print(f"\n=== iframe 개수: {len(iframes)} ===")
    for i, frame in enumerate(iframes):
        print(f"  iframe[{i}] id={frame.get_attribute('id')} src={frame.get_attribute('src')}")

    input("\n브라우저 창 확인 후 엔터 누르면 종료...")

finally:
    driver.quit()
