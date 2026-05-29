"""
klas_assignment.py
KLAS 로그인 후 4가지 정보 크롤링:
  1. 과제     : /std/lis/evltn/TaskStdPage.do
  2. 팀프로젝트: /std/lis/evltn/PrjctStdPage.do
  3. 온라인강의: /std/lis/evltn/OnlineCntntsStdPage.do (과목별)
  4. 강의실   : /std/lis/evltn/LctrumHomeStdPage.do   (과목별 현황)

실행:
    python klas_assignment.py
"""

import re
import time
import json
import logging
import os
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://klas.kw.ac.kr"


# ──────────────────────────────────────────────
# 우선순위 레이블
# ──────────────────────────────────────────────

def priority_label(days_left: Optional[int]) -> str:
    if days_left is None:
        return "⚪"
    if days_left < 0:
        return "💀 마감됨"
    if days_left == 0:
        return "🔴 오늘마감"
    if days_left <= 3:
        return "🔴 긴급"
    if days_left <= 7:
        return "🟠 이번주"
    if days_left <= 14:
        return "🟡 2주내"
    return "🟢 여유"


# ──────────────────────────────────────────────
# 데이터 모델
# ──────────────────────────────────────────────

@dataclass
class Task:
    task_type: str
    course_name: str
    title: str
    due_str: str
    due_date: Optional[date]
    is_done: bool
    days_left: Optional[int]

    def display(self) -> str:
        status = "✅" if self.is_done else "❌"
        p_label = priority_label(self.days_left) if not self.is_done else ""
        return f"{status} {p_label} [{self.task_type}] {self.course_name}: {self.title} (마감: {self.due_str})"


# ──────────────────────────────────────────────
# KLAS 크롤러
# ──────────────────────────────────────────────

class KLASCrawler:

    TASK_URL    = f"{BASE_URL}/std/lis/evltn/TaskStdPage.do"
    PROJECT_URL = f"{BASE_URL}/std/lis/evltn/PrjctStdPage.do"
    ONLINE_URL  = f"{BASE_URL}/std/lis/evltn/OnlineCntntsStdPage.do"
    HOME_URL    = f"{BASE_URL}/std/lis/evltn/LctrumHomeStdPage.do"
    LOGIN_URL   = f"{BASE_URL}/usr/cmn/login/LoginForm.do"

    def __init__(self, headless: bool = True):
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=ko-KR")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        self.driver    = webdriver.Chrome(options=options)
        self.wait      = WebDriverWait(self.driver, 15)
        self.logged_in = False
        self._courses  = []  # [(index, name)] 캐시

    # ── 로그인 ──────────────────────────────────

    def login(self, student_id: str, password: str) -> bool:
        logger.info("[KLAS] 로그인 중...")
        try:
            self.driver.get(self.LOGIN_URL)
            self.wait.until(EC.presence_of_element_located((By.ID, "loginId")))
            self.driver.find_element(By.ID, "loginId").send_keys(student_id)
            self.driver.find_element(By.ID, "loginPwd").send_keys(password)
            for sel in ["button[type='submit']", ".btn-login"]:
                try:
                    self.driver.find_element(By.CSS_SELECTOR, sel).click()
                    break
                except:
                    continue
            time.sleep(3)
            try:
                alert = self.driver.switch_to.alert
                msg   = alert.text
                alert.accept()
                logger.error(f"[KLAS] 로그인 실패: {msg}")
                return False
            except:
                pass
            if "LoginForm" not in self.driver.current_url:
                self.logged_in = True
                logger.info("[KLAS] 로그인 성공!")
                return True
            return False
        except Exception as e:
            logger.error(f"[KLAS] 오류: {e}")
            return False

    # ── 날짜 파싱 ────────────────────────────────

    def _parse_due(self, raw: str):
        """마감일 파싱 → (due_date, due_str, days_left)"""
        if not raw or raw.strip() == "":
            return None, "마감일 미정", None

        raw = raw.strip()
        dt  = None
        patterns = [
            ("%Y-%m-%d %H:%M:%S", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y-%m-%d %H:%M",    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
            ("%Y.%m.%d %H:%M:%S", r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y.%m.%d %H:%M",    r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}"),
            ("%Y-%m-%d",          r"\d{4}-\d{2}-\d{2}"),
            ("%Y.%m.%d",          r"\d{4}\.\d{2}\.\d{2}"),
        ]
        for fmt, pattern in patterns:
            # ~ 뒤 종료일 우선
            m = re.search(r"~\s*(" + pattern + r")", raw)
            if m:
                try:
                    dt = datetime.strptime(m.group(1).strip(), fmt)
                    break
                except:
                    pass
            m = re.search(pattern, raw)
            if m:
                try:
                    dt = datetime.strptime(m.group(), fmt)
                    break
                except:
                    continue

        if not dt:
            return None, raw[:20], None

        today     = date.today()
        days_left = (dt.date() - today).days

        if days_left < 0:
            due_str = f"{dt.strftime('%m/%d')} 마감됨"
        elif days_left == 0:
            due_str = f"오늘 {dt.strftime('%H:%M')}"
        elif days_left <= 7:
            due_str = f"D-{days_left} ({dt.strftime('%m/%d')})"
        else:
            due_str = dt.strftime("%m/%d")

        return dt.date(), due_str, days_left

    # ── 과목 드롭다운 ────────────────────────────

    def _get_course_options(self) -> List[tuple]:
        """드롭다운에서 과목 목록 추출 → [(index, name)]"""
        if self._courses:
            return self._courses
        courses = []
        try:
            selects = self.driver.find_elements(By.CSS_SELECTOR, "select")
            target  = None
            for sel in selects:
                opts = sel.find_elements(By.TAG_NAME, "option")
                for opt in opts:
                    if "I030" in opt.text or any(k in opt.text for k in ["디지털", "소프트", "알고리즘", "컴퓨터", "응용"]):
                        target = sel
                        break
                if target:
                    break
            if not target and selects:
                target = max(selects, key=lambda s: len(s.find_elements(By.TAG_NAME, "option")))
            if target:
                for i, opt in enumerate(target.find_elements(By.TAG_NAME, "option")):
                    name = opt.text.strip()
                    if name:
                        courses.append((i, name, target))
        except Exception as e:
            logger.warning(f"[과목목록] {e}")
        self._courses = courses
        return courses

    def _select_course(self, idx: int, courses: list):
        """index로 과목 선택 (value=[object Object]라 click 사용)"""
        try:
            selects = self.driver.find_elements(By.CSS_SELECTOR, "select")
            target  = None
            for sel in selects:
                opts = sel.find_elements(By.TAG_NAME, "option")
                for opt in opts:
                    if "I030" in opt.text or any(k in opt.text for k in ["디지털", "소프트", "알고리즘", "컴퓨터", "응용"]):
                        target = sel
                        break
                if target:
                    break
            if target:
                opts = target.find_elements(By.TAG_NAME, "option")
                if idx < len(opts):
                    opts[idx].click()
                    time.sleep(1.5)
                    return True
        except Exception as e:
            logger.warning(f"[과목선택] {e}")
        return False

    # ── 1. 과제 크롤링 ──────────────────────────

    def get_assignments(self) -> List[Task]:
        """TaskStdPage.do — 과제 수집"""
        logger.info("[KLAS] 과제 수집 중...")
        self.driver.get(self.TASK_URL)
        time.sleep(2)

        tasks   = []
        courses = self._get_course_options()
        logger.info(f"[KLAS] 과목 {len(courses)}개")

        for idx, name, _ in courses:
            try:
                self._select_course(idx, courses)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")

                for table in soup.find_all("table"):
                    headers = [th.get_text(strip=True) for th in table.find_all("th")]
                    if "과제 제목" not in headers or "제출기한" not in headers:
                        continue

                    title_idx  = headers.index("과제 제목")
                    date_idx   = headers.index("제출기한")
                    status_idx = headers.index("상태") if "상태" in headers else -1

                    for row in table.find_all("tr")[1:]:
                        cols = row.find_all("td")
                        if len(cols) <= title_idx:
                            continue
                        title = cols[title_idx].get_text(strip=True)
                        if not title or len(title) < 2:
                            continue

                        date_raw  = cols[date_idx].get_text(strip=True) if date_idx < len(cols) else ""
                        is_done   = False
                        if status_idx >= 0 and status_idx < len(cols):
                            is_done = cols[status_idx].get_text(strip=True) == "제출"

                        due_date, due_str, days_left = self._parse_due(date_raw)
                        if days_left is not None and days_left < -7:
                            continue

                        task_type = "프로젝트" if any(k in title for k in ["Project", "프로젝트"]) else "과제"
                        tasks.append(Task(task_type, name, title, due_str, due_date, is_done, days_left))

                logger.info(f"  과제 {name}: {sum(1 for t in tasks if t.course_name == name and t.task_type in ['과제','프로젝트'])}개")
            except Exception as e:
                logger.warning(f"  과제 {name} 실패: {e}")

        logger.info(f"[KLAS] 과제 총 {len(tasks)}개")
        return tasks

    # ── 2. 팀프로젝트 크롤링 ────────────────────

    def get_projects(self) -> List[Task]:
        """PrjctStdPage.do — 팀프로젝트 수집"""
        logger.info("[KLAS] 팀프로젝트 수집 중...")
        self._courses = []  # 드롭다운 캐시 초기화
        self.driver.get(self.PROJECT_URL)
        time.sleep(2)

        tasks   = []
        courses = self._get_course_options()

        for idx, name, _ in courses:
            try:
                self._select_course(idx, courses)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")

                for table in soup.find_all("table"):
                    headers = [th.get_text(strip=True) for th in table.find_all("th")]
                    if not any(h in headers for h in ["팀프로젝트명", "제목", "프로젝트명"]):
                        continue

                    for row in table.find_all("tr")[1:]:
                        cols = row.find_all("td")
                        if len(cols) < 2:
                            continue

                        title    = cols[1].get_text(strip=True) if len(cols) > 1 else cols[0].get_text(strip=True)
                        date_raw = ""
                        status   = ""

                        for col in cols:
                            text = col.get_text(strip=True)
                            if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                                date_raw = text
                            if text in ["제출", "미제출", "미제출(재제출가능)"]:
                                status = text

                        if not title or len(title) < 2:
                            continue

                        is_done   = status == "제출"
                        due_date, due_str, days_left = self._parse_due(date_raw)
                        if days_left is not None and days_left < -7:
                            continue

                        tasks.append(Task("팀프로젝트", name, title, due_str, due_date, is_done, days_left))

            except Exception as e:
                logger.warning(f"  팀프로젝트 {name} 실패: {e}")

        logger.info(f"[KLAS] 팀프로젝트 {len(tasks)}개")
        return tasks

    # ── 3. 온라인강의 크롤링 ─────────────────────

    def get_online_lectures(self) -> List[Task]:
        """
        OnlineCntntsStdPage.do — 온라인강의 미수강 수집
        달성시간 < 인정시간 인 항목만 추출
        """
        logger.info("[KLAS] 온라인강의 수집 중...")
        self._courses = []
        self.driver.get(self.ONLINE_URL)
        time.sleep(2)

        tasks   = []
        courses = self._get_course_options()

        for idx, name, _ in courses:
            try:
                self._select_course(idx, courses)
                soup = BeautifulSoup(self.driver.page_source, "html.parser")

                for table in soup.find_all("table"):
                    headers = [th.get_text(strip=True) for th in table.find_all("th")]

                    # 온라인강의 테이블 판별
                    if not any(h in headers for h in ["학습목차", "강의명", "학습목표"]):
                        continue

                    # 인정시간, 달성시간 컬럼 인덱스
                    cert_idx  = -1
                    reach_idx = -1
                    date_idx  = -1
                    title_idx = -1

                    for i, h in enumerate(headers):
                        if "학습목차" in h or "강의명" in h:
                            title_idx = i
                        if "인정시간" in h:
                            cert_idx = i
                        if "달성시간" in h:
                            reach_idx = i
                        if "학습기간" in h or "기간" in h:
                            date_idx = i

                    for row in table.find_all("tr")[1:]:
                        cols = row.find_all("td")
                        if len(cols) < 2:
                            continue

                        # 제목
                        t_idx = title_idx if title_idx >= 0 and title_idx < len(cols) else 1
                        title = cols[t_idx].get_text(strip=True)
                        if not title or len(title) < 2:
                            continue

                        # 달성시간 / 인정시간 비교
                        is_done = True
                        if cert_idx >= 0 and reach_idx >= 0:
                            cert  = cols[cert_idx].get_text(strip=True)  if cert_idx  < len(cols) else ""
                            reach = cols[reach_idx].get_text(strip=True) if reach_idx < len(cols) else ""
                            # "38/38" 또는 "0/38" 형태
                            if reach and cert:
                                try:
                                    r_num = int(re.sub(r"[^0-9]", "", reach.split("/")[0]))
                                    c_num = int(re.sub(r"[^0-9]", "", cert))
                                    is_done = r_num >= c_num
                                except:
                                    is_done = "100%" in reach or reach == cert
                        elif reach_idx >= 0:
                            reach = cols[reach_idx].get_text(strip=True)
                            is_done = "100%" in reach

                        # 미수강만 추가
                        if is_done:
                            continue

                        # 마감일
                        date_raw = ""
                        if date_idx >= 0 and date_idx < len(cols):
                            date_raw = cols[date_idx].get_text(strip=True)
                        else:
                            for col in cols:
                                text = col.get_text(strip=True)
                                if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                                    date_raw = text
                                    break

                        due_date, due_str, days_left = self._parse_due(date_raw)
                        if days_left is not None and days_left < -7:
                            continue

                        tasks.append(Task("온라인강의", name, title, due_str, due_date, False, days_left))

            except Exception as e:
                logger.warning(f"  온라인강의 {name} 실패: {e}")

        logger.info(f"[KLAS] 온라인강의 미수강 {len(tasks)}개")
        return tasks

    # ── 전체 수집 ────────────────────────────────

    def collect_all(self) -> List[Task]:
        all_tasks = []
        all_tasks.extend(self.get_assignments())

        self._courses = []
        all_tasks.extend(self.get_projects())

        self._courses = []
        all_tasks.extend(self.get_online_lectures())

        # 중복 제거
        seen, unique = set(), []
        for t in all_tasks:
            key = f"{t.course_name}_{t.task_type}_{t.title}"
            if key not in seen:
                seen.add(key)
                unique.append(t)

        return unique

    def close(self):
        if self.driver:
            self.driver.quit()


# ──────────────────────────────────────────────
# LLM 우선순위 정렬
# ──────────────────────────────────────────────

def sort_by_llm(tasks: List[Task]) -> List[Task]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("[LLM] API 키 없음 → 마감일 순 정렬")
        return sorted(tasks, key=lambda t: (
            t.is_done,
            t.days_left if t.days_left is not None else 9999
        ))

    try:
        import anthropic
        client    = anthropic.Anthropic(api_key=api_key)
        today_str = date.today().strftime("%Y년 %m월 %d일")
        task_list = "\n".join([
            f"{i+1}. [{t.task_type}] {t.course_name}: {t.title} "
            f"(마감: {t.due_str}, {'완료' if t.is_done else '미완료'})"
            for i, t in enumerate(tasks)
        ])
        prompt = f"""오늘 날짜: {today_str}

아래 할 일 목록을 긴급도 순서로 정렬해줘.
- 미완료 항목을 완료보다 앞에
- 마감 임박한 순서대로
- 마감일 없는 항목은 마지막

{task_list}

정렬된 번호 순서만 JSON 배열로 반환. 예: [3, 1, 4, 2]
JSON 배열만 반환해."""

        msg   = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        match = re.search(r"\[[\d,\s]+\]", msg.content[0].text.strip())
        if match:
            order        = json.loads(match.group())
            sorted_tasks = []
            used         = set()
            for idx in order:
                if 1 <= idx <= len(tasks):
                    sorted_tasks.append(tasks[idx - 1])
                    used.add(idx)
            for i, t in enumerate(tasks, 1):
                if i not in used:
                    sorted_tasks.append(t)
            logger.info("[LLM] 우선순위 정렬 완료")
            return sorted_tasks
    except Exception as e:
        logger.warning(f"[LLM] 실패, 마감일 순 폴백: {e}")

    return sorted(tasks, key=lambda t: (
        t.is_done,
        t.days_left if t.days_left is not None else 9999
    ))


# ──────────────────────────────────────────────
# 실행
# ──────────────────────────────────────────────

def main():
    student_id = input("학번: ").strip()
    password   = input("비밀번호: ").strip()

    crawler = KLASCrawler(headless=True)
    try:
        if not crawler.login(student_id, password):
            print("❌ 로그인 실패")
            return

        print("\n📡 KLAS에서 정보 수집 중...")
        tasks = crawler.collect_all()

        if not tasks:
            print("수집된 항목이 없습니다.")
            return

        print("🤖 AI가 우선순위 정렬 중...")
        tasks = sort_by_llm(tasks)

        today_str = date.today().strftime("%Y년 %m월 %d일")
        print(f"\n{'='*65}")
        print(f"📋 오늘 할 일 ({today_str})")
        print(f"{'='*65}\n")

        for task in tasks:
            print(task.display())

        print(f"\n{'='*65}")
        total      = len(tasks)
        undone     = sum(1 for t in tasks if not t.is_done)
        urgent     = sum(1 for t in tasks if not t.is_done and t.days_left is not None and t.days_left <= 3)
        print(f"🔴 긴급(3일이내): {urgent}개  |  미완료: {undone}개  |  전체: {total}개")

    finally:
        crawler.close()


if __name__ == "__main__":
    main()
