"""
check_klas.py
KLAS 과제 페이지 실제 HTML 구조 확인용 스크립트
"""
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

student_id = input("학번: ").strip()
password   = input("비밀번호: ").strip()

# Chrome 실행 (창 보이게)
options = Options()
options.add_argument("--window-size=1920,1080")
options.add_argument("--lang=ko-KR")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

driver = webdriver.Chrome(options=options)
wait   = WebDriverWait(driver, 15)

try:
    # 1. 로그인
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
    print(f"현재 URL: {driver.current_url}")

    # 2. 과제 페이지 접속
    print("\n과제 페이지 접속 중...")
    driver.get("https://klas.kw.ac.kr/std/lis/evltn/TaskStdPage.do")
    time.sleep(2)

    # 3. 드롭다운 확인
    selects = driver.find_elements(By.CSS_SELECTOR, "select")
    print(f"\n드롭다운 개수: {len(selects)}")
    for i, sel in enumerate(selects):
        opts = sel.find_elements(By.TAG_NAME, "option")
        print(f"  드롭다운[{i}] 옵션 수: {len(opts)}")
        for opt in opts[:5]:
            print(f"    value='{opt.get_attribute('value')}' text='{opt.text.strip()}'")

    # 4. 첫 번째 과목 선택 후 테이블 확인
    if selects:
        opts = selects[0].find_elements(By.TAG_NAME, "option")
        if len(opts) > 1:
            first_val = opts[1].get_attribute("value")
            Select(selects[0]).select_by_value(first_val)
            time.sleep(1.5)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    # 5. 테이블 헤더 확인
    print("\n=== 테이블 구조 ===")
    for i, table in enumerate(soup.find_all("table")):
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if headers:
            print(f"\n테이블[{i}] 헤더: {headers}")
            # 첫 번째 행 데이터
            rows = table.find_all("tr")[1:3]
            for row in rows:
                cols = [td.get_text(strip=True) for td in row.find_all("td")]
                print(f"  데이터: {cols}")

    # 6. HTML 저장
    with open("task_page.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("\ntask_page.html 저장 완료!")

    input("\n확인 후 엔터 누르면 종료...")

finally:
    driver.quit()
