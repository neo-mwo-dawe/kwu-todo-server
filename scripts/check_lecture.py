"""
check_lecture.py
KLAS 온라인강의 페이지 실제 HTML 구조 확인
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

student_id = input("학번: ").strip()
password   = input("비밀번호: ").strip()

options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--lang=ko-KR")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

driver = webdriver.Chrome(options=options)
wait   = WebDriverWait(driver, 15)

try:
    # 로그인
    print("로그인 중...")
    driver.get("https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do")
    wait.until(EC.presence_of_element_located((By.ID, "loginId")))
    driver.find_element(By.ID, "loginId").send_keys(student_id)
    driver.find_element(By.ID, "loginPwd").send_keys(password)
    for selector in ["button[type='submit']", ".btn-login"]:
        try:
            driver.find_element(By.CSS_SELECTOR, selector).click()
            break
        except:
            continue
    time.sleep(3)
    print(f"URL: {driver.current_url}")

    # 온라인강의 페이지
    print("\n온라인강의 페이지 접속...")
    driver.get("https://klas.kw.ac.kr/std/lis/evltn/LctrumStdPage.do")
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # 테이블 구조 확인
    print("\n=== 테이블 구조 ===")
    for i, table in enumerate(soup.find_all("table")):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if headers:
            print(f"\n테이블[{i}] 헤더: {headers}")
            for row in table.find_all("tr")[1:4]:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                if cols:
                    print(f"  데이터: {cols}")

    # 전체 텍스트에서 미수강 키워드 찾기
    print("\n=== 미수강 관련 텍스트 ===")
    full_text = soup.get_text()
    keywords = ["미시청", "미완료", "출석", "강의", "수강"]
    for kw in keywords:
        count = full_text.count(kw)
        if count > 0:
            print(f"  '{kw}' 발견: {count}회")

    # HTML 저장
    with open("lecture_page.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("\nlecture_page.html 저장 완료!")

    input("\n확인 후 엔터 누르면 종료...")

finally:
    driver.quit()
