"""
check_all.py
4개 URL 실제 HTML 구조 한번에 확인
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
    driver.get("https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do")
    wait.until(EC.presence_of_element_located((By.ID, "loginId")))
    driver.find_element(By.ID, "loginId").send_keys(student_id)
    driver.find_element(By.ID, "loginPwd").send_keys(password)
    for sel in ["button[type='submit']", ".btn-login"]:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            break
        except:
            continue
    time.sleep(3)
    print(f"로그인 URL: {driver.current_url}\n")

    urls = {
        "과제":      "https://klas.kw.ac.kr/std/lis/evltn/TaskStdPage.do",
        "팀프로젝트": "https://klas.kw.ac.kr/std/lis/evltn/PrjctStdPage.do",
        "온라인강의": "https://klas.kw.ac.kr/std/lis/evltn/OnlineCntntsStdPage.do",
    }

    for page_name, url in urls.items():
        print(f"\n{'='*50}")
        print(f"[{page_name}] {url}")
        print('='*50)
        driver.get(url)
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        # 드롭다운
        selects = driver.find_elements(By.CSS_SELECTOR, "select")
        print(f"드롭다운 수: {len(selects)}")
        for sel in selects:
            opts = sel.find_elements(By.TAG_NAME, "option")
            if len(opts) > 1:
                print(f"  옵션: {[o.text.strip() for o in opts[:3]]}")

        # 테이블
        for i, table in enumerate(soup.find_all("table")):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if headers:
                print(f"\n  테이블[{i}] 헤더: {headers}")
                for row in table.find_all("tr")[1:3]:
                    cols = [td.get_text(strip=True) for td in row.find_all("td")]
                    if cols:
                        print(f"    데이터: {cols}")

        # HTML 저장
        with open(f"{page_name}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"\n  {page_name}.html 저장 완료!")

    input("\n확인 후 엔터...")
finally:
    driver.quit()
