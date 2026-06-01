"""
klas_crawler.py
광운대학교 KLAS Selenium 기반 실제 로그인 및 데이터 크롤링 모듈
- 수강과목 목록 수집
- 각 과목별 과제/퀴즈 페이지 접근하여 마감일 수집
"""

import logging
import re
import time
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Optional, List

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class TodayTask:
    title: str
    course_name: str
    task_type: str
    due_date: Optional[datetime] = None
    due_str: str = ""
    priority: int = 2
    url: str = ""
    description: str = ""

    @property
    def priority_label(self) -> str:
        return {1: "🔴 긴급", 2: "🟠 이번주", 3: "🟡 보통"}.get(self.priority, "🟢 여유")

    @property
    def days_left(self) -> Optional[int]:
        if not self.due_date:
            return None
        return (self.due_date.date() - date.today()).days


@dataclass
class StudentInfo:
    student_id: str = ""
    name: str = ""
    department: str = ""
    grade: str = ""
    semester: str = ""


class KLASClient:
    """Selenium 기반 KLAS 로그인 및 과목별 과제 수집"""

    LOGIN_URL   = "https://klas.kw.ac.kr/usr/cmn/login/LoginForm.do"
    MAIN_URL    = "https://klas.kw.ac.kr/std/cmn/frame/DashBoardStdPage.do"
    TASK_URL    = "https://klas.kw.ac.kr/std/lis/evltn/TaskStdPage.do"
    QUIZ_URL    = "https://klas.kw.ac.kr/std/lis/evltn/AnytmQuizStdPage.do"
    # ✅ [추가] 팀프로젝트 페이지 URL
    PROJECT_URL = "https://klas.kw.ac.kr/std/lis/evltn/PrjctStdPage.do"

    def __init__(self):
        self.driver = None
        self.logged_in = False
        self.student_info = StudentInfo()
        self._courses = []   # 수강 과목 목록 캐시

    def _init_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=ko-KR")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(5)

    def login(self, student_id: str, password: str) -> dict:
        try:
            self._init_driver()
            wait = WebDriverWait(self.driver, 15)

            self.driver.get(self.LOGIN_URL)
            wait.until(EC.presence_of_element_located((By.ID, "loginId")))
            self.driver.find_element(By.ID, "loginId").send_keys(student_id)
            self.driver.find_element(By.ID, "loginPwd").send_keys(password)

            # 로그인 버튼 클릭
            for selector in ["button[type='submit']", ".btn-login", "input[type='submit']", "a.btn"]:
                try:
                    btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                    btn.click()
                    break
                except:
                    continue

            # 로그인 결과 확인
            time.sleep(2)

            # alert 확인
            try:
                alert = self.driver.switch_to.alert
                msg = alert.text
                alert.accept()
                return {"success": False, "message": msg, "student": None}
            except:
                pass

            # URL 변경 확인
            if "LoginForm" not in self.driver.current_url:
                self.logged_in = True
                self.student_info.student_id = student_id
                self.student_info.semester = self._get_current_semester()
                self._fetch_student_info()
                logger.info(f"[KLAS] 로그인 성공: {student_id}")
                return {"success": True, "message": "로그인 성공", "student": self.student_info}
            else:
                return {"success": False, "message": "학번 또는 비밀번호가 올바르지 않습니다.", "student": None}

        except Exception as e:
            logger.error(f"[KLAS] 로그인 오류: {e}")
            if self.driver:
                self.driver.quit()
                self.driver = None
            return {"success": False, "message": f"오류: {str(e)}", "student": None}

    def _fetch_student_info(self):
        try:
            # 학생 이름 추출
            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            for selector in [".user-name", "#userName", ".nm", ".name", ".user_name"]:
                el = soup.select_one(selector)
                if el and el.get_text(strip=True):
                    self.student_info.name = el.get_text(strip=True)
                    break
        except:
            pass

    def _get_current_semester(self) -> str:
        now = datetime.now()
        return f"{now.year}년 {1 if now.month <= 6 else 2}학기"

    def _get_courses(self) -> List[dict]:
        """메인 대시보드에서 수강 과목 목록 수집"""
        if self._courses:
            return self._courses

        courses = []
        try:
            self.driver.get(self.MAIN_URL)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            for el in soup.select(".course-name, .subject-name, .crs-nm, .gwMjNm"):
                name = el.get_text(strip=True)
                if name and len(name) > 2:
                    courses.append({"name": name, "id": ""})

            if not courses:
                for el in soup.find_all(["a", "span", "div"]):
                    text = el.get_text(strip=True)
                    if re.search(r'I\d{3,4}-\d-\d{4}-\d{2}', text):
                        courses.append({"name": text, "id": ""})

            if not courses:
                logger.info("[KLAS] 대시보드 파싱 실패, 과목 페이지 직접 접근 시도")

            self._courses = courses
            logger.info(f"[KLAS] 수강 과목 {len(courses)}개 수집")

        except Exception as e:
            logger.error(f"[KLAS] 과목 목록 수집 오류: {e}")

        return courses

    def get_today_tasks(self) -> List[TodayTask]:
        """모든 수강과목의 과제/퀴즈 수집"""
        if not self.logged_in or not self.driver:
            return []

        tasks = []

        # 1. 과제 수집 (TaskStdPage)
        tasks.extend(self._fetch_tasks())

        # 2. 퀴즈 수집 (AnytmQuizStdPage)
        tasks.extend(self._fetch_quizzes())

        # ✅ [추가] 3. 팀프로젝트 수집 (PrjctStdPage)
        tasks.extend(self._fetch_projects())

        # 4. 학사일정 수집  ← 기존 3번에서 4번으로 번호만 변경
        tasks.extend(self._fetch_academic_calendar())

        # 중복 제거 및 정렬
        seen = set()
        unique = []
        for t in tasks:
            key = f"{t.course_name}_{t.title}"
            if key not in seen:
                seen.add(key)
                unique.append(t)

        unique.sort(key=lambda t: (t.priority, t.due_date or datetime.max))
        logger.info(f"[KLAS] 총 {len(unique)}개 할 일 수집")
        return unique

    def _fetch_tasks(self) -> List[TodayTask]:
        """과제 제출 페이지에서 과제 목록 수집"""
        tasks = []
        try:
            self.driver.get(self.TASK_URL)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            course_options = []
            select_el = soup.select_one("select[name*='crs'], select[name*='course'], #selectGwNo, .selectGwNo")
            if select_el:
                for opt in select_el.find_all("option"):
                    val = opt.get("value", "")
                    name = opt.get_text(strip=True)
                    if val and name and val != "":
                        course_options.append({"value": val, "name": name})

            logger.info(f"[KLAS] 과제 페이지 과목 수: {len(course_options)}")

            if course_options:
                for course in course_options:
                    tasks.extend(self._fetch_task_for_course(course))
            else:
                tasks.extend(self._parse_task_table(soup, "전체"))

        except Exception as e:
            logger.error(f"[KLAS] 과제 수집 오류: {e}")

        return tasks

    def _fetch_task_for_course(self, course: dict) -> List[TodayTask]:
        """특정 과목의 과제 수집"""
        tasks = []
        try:
            select_el = self.driver.find_element(
                By.CSS_SELECTOR, "select[name*='crs'], select[name*='course'], #selectGwNo, .selectGwNo"
            )
            from selenium.webdriver.support.ui import Select
            Select(select_el).select_by_value(course["value"])
            time.sleep(1.5)

            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            tasks = self._parse_task_table(soup, course["name"])

        except Exception as e:
            logger.warning(f"[KLAS] {course['name']} 과제 수집 실패: {e}")

        return tasks

    def _parse_task_table(self, soup: BeautifulSoup, course_name: str) -> List[TodayTask]:
        """과제 테이블 파싱"""
        tasks = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if not any(h in ["과제 제목", "제목", "과제명"] for h in headers):
                continue

            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                title = cols[1].get_text(strip=True) if len(cols) > 1 else cols[0].get_text(strip=True)
                date_text = ""

                for col in cols:
                    text = col.get_text(strip=True)
                    if re.search(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                        date_text = text
                        break

                if title and len(title) > 1:
                    due_date, due_str, priority = self._parse_due(date_text)
                    if due_date and (due_date.date() - date.today()).days < -7:
                        continue

                    link_tag = cols[1].find("a") if len(cols) > 1 else None
                    url = ""
                    if link_tag and link_tag.get("href"):
                        href = link_tag.get("href")
                        url = href if href.startswith("http") else "https://klas.kw.ac.kr" + href

                    tasks.append(TodayTask(
                        title=title,
                        course_name=course_name,
                        task_type="과제",
                        due_date=due_date,
                        due_str=due_str,
                        priority=priority,
                        url=url,
                    ))

        return tasks

    # ✅ [추가] 팀프로젝트 수집 메서드 3개 ─────────────────────────────────────

    def _fetch_projects(self) -> List[TodayTask]:
        """팀프로젝트 페이지(PrjctStdPage)에서 프로젝트 목록 수집"""
        tasks = []
        try:
            self.driver.get(self.PROJECT_URL)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            course_options = []
            select_el = soup.select_one(
                "select[name*='crs'], select[name*='course'], #selectGwNo, .selectGwNo"
            )
            if select_el:
                for opt in select_el.find_all("option"):
                    val  = opt.get("value", "")
                    name = opt.get_text(strip=True)
                    if val and name and val != "":
                        course_options.append({"value": val, "name": name})

            logger.info(f"[KLAS] 팀프로젝트 페이지 과목 수: {len(course_options)}")

            if course_options:
                for course in course_options:
                    tasks.extend(self._fetch_project_for_course(course))
            else:
                tasks.extend(self._parse_project_table(soup, "전체"))

        except Exception as e:
            logger.error(f"[KLAS] 팀프로젝트 수집 오류: {e}")

        return tasks

    def _fetch_project_for_course(self, course: dict) -> List[TodayTask]:
        """특정 과목의 팀프로젝트 수집"""
        tasks = []
        try:
            select_el = self.driver.find_element(
                By.CSS_SELECTOR,
                "select[name*='crs'], select[name*='course'], #selectGwNo, .selectGwNo"
            )
            from selenium.webdriver.support.ui import Select
            Select(select_el).select_by_value(course["value"])
            time.sleep(1.5)

            soup = BeautifulSoup(self.driver.page_source, "html.parser")
            tasks = self._parse_project_table(soup, course["name"])

        except Exception as e:
            logger.warning(f"[KLAS] {course['name']} 팀프로젝트 수집 실패: {e}")

        return tasks

    def _parse_project_table(self, soup: BeautifulSoup, course_name: str) -> List[TodayTask]:
        """팀프로젝트 테이블 파싱

        KLAS PrjctStdPage 컬럼 구조 (일반적):
          번호 | 프로젝트명 | 분류 | 팀명 | 제출기간(시작~종료) | 제출여부
        """
        tasks = []
        for table in soup.find_all("table"):
            headers = [th.get_text(strip=True) for th in table.find_all("th")]

            is_project_table = any(
                h in ["프로젝트명", "제목", "과제명", "팀프로젝트", "프로젝트 제목"]
                for h in headers
            )
            if not is_project_table:
                continue

            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 2:
                    continue

                title = ""
                url   = ""
                for i, col in enumerate(cols):
                    text = col.get_text(strip=True)
                    if text.isdigit():                                      # 번호 컬럼 스킵
                        continue
                    if text in ("미제출", "제출", "완료", "-"):             # 제출여부 컬럼 스킵
                        continue
                    if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):      # 날짜 컬럼 스킵
                        continue
                    if len(text) > len(title):                              # 가장 긴 텍스트 = 제목
                        title = text
                        link_tag = col.find("a")
                        if link_tag and link_tag.get("href"):
                            href = link_tag["href"]
                            url = href if href.startswith("http") else "https://klas.kw.ac.kr" + href

                # 날짜: "시작일 ~ 종료일" 형태 탐색, 범위(~) 우선
                date_text = ""
                for col in cols:
                    text = col.get_text(strip=True)
                    if "~" in text and re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                        date_text = text
                        break
                    if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                        date_text = text

                if not title or len(title) <= 1:
                    continue

                due_date, due_str, priority = self._parse_due(date_text)

                if due_date and (due_date.date() - date.today()).days < -7:
                    continue

                tasks.append(TodayTask(
                    title=title,
                    course_name=course_name,
                    task_type="팀프로젝트",      # ← 기존 "과제"/"퀴즈"와 구분되는 새 타입
                    due_date=due_date,
                    due_str=due_str,
                    priority=priority,
                    url=url,
                ))

        return tasks

    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_quizzes(self) -> List[TodayTask]:
        """수시퀴즈 페이지에서 퀴즈 목록 수집"""
        tasks = []
        try:
            self.driver.get(self.QUIZ_URL)
            time.sleep(2)
            soup = BeautifulSoup(self.driver.page_source, "html.parser")

            for table in soup.find_all("table"):
                for row in table.find_all("tr")[1:]:
                    cols = row.find_all("td")
                    if len(cols) < 2:
                        continue
                    title = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                    course = cols[0].get_text(strip=True)
                    date_text = ""
                    for col in cols:
                        text = col.get_text(strip=True)
                        if re.search(r'\d{4}[-./]\d{2}[-./]\d{2}', text):
                            date_text = text
                            break

                    if title and len(title) > 1:
                        due_date, due_str, priority = self._parse_due(date_text)
                        if due_date and (due_date.date() - date.today()).days < -7:
                            continue
                        tasks.append(TodayTask(
                            title=title,
                            course_name=course,
                            task_type="퀴즈",
                            due_date=due_date,
                            due_str=due_str,
                            priority=priority,
                        ))

        except Exception as e:
            logger.warning(f"[KLAS] 퀴즈 수집 오류: {e}")

        return tasks

    def _fetch_academic_calendar(self) -> List[TodayTask]:
        """광운대 학사일정 수집"""
        import requests
        tasks = []
        try:
            resp = requests.get("https://www.kw.ac.kr/ko/life/academic-calendar.jsp", timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            today = date.today()

            for table in soup.find_all("table"):
                for row in table.find_all("tr")[1:]:
                    cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                    if len(cols) < 2:
                        continue
                    date_str, title = cols[0], cols[-1]
                    parsed_date = self._parse_simple_date(date_str)
                    if parsed_date and 0 <= (parsed_date - today).days <= 14:
                        tasks.append(TodayTask(
                            title=title,
                            course_name="학사일정",
                            task_type="학사일정",
                            due_date=datetime.combine(parsed_date, datetime.min.time()),
                            due_str=parsed_date.strftime("%m/%d"),
                            priority=1 if (parsed_date - today).days <= 1 else 2,
                        ))
        except Exception as e:
            logger.warning(f"[학사일정] 수집 오류: {e}")

        return tasks

    def _parse_due(self, raw: str):
        if not raw:
            return None, "마감일 미정", 3
        raw = raw.strip()
        dt = None
        patterns = [
            ("%Y.%m.%d %H:%M:%S", r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y.%m.%d %H:%M",    r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}"),
            ("%Y-%m-%d %H:%M:%S", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
            ("%Y-%m-%d %H:%M",    r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"),
            ("%Y.%m.%d",          r"\d{4}\.\d{2}\.\d{2}"),
            ("%Y-%m-%d",          r"\d{4}-\d{2}-\d{2}"),
        ]
        for fmt, pattern in patterns:
            range_match = re.search(r'~\s*(' + pattern + r')', raw)
            if range_match:
                try:
                    dt = datetime.strptime(range_match.group(1).strip(), fmt)
                    break
                except:
                    pass
            match = re.search(pattern, raw)
            if match:
                try:
                    dt = datetime.strptime(match.group(), fmt)
                    break
                except:
                    continue

        if not dt:
            return None, raw[:20], 3

        today = date.today()
        days = (dt.date() - today).days

        if days < 0:
            return dt, f"⚠️ 마감됨 ({dt.strftime('%m/%d')})", 1
        elif days == 0:
            return dt, f"오늘 {dt.strftime('%H:%M')} 마감", 1
        elif days == 1:
            return dt, f"내일 {dt.strftime('%H:%M')} 마감", 1
        elif days <= 3:
            return dt, f"{days}일 후 ({dt.strftime('%m/%d')})", 2
        elif days <= 7:
            return dt, f"{dt.strftime('%m/%d')} 마감 ({days}일)", 2
        else:
            return dt, f"{dt.strftime('%m/%d')} 마감 ({days}일)", 3

    def _parse_simple_date(self, raw: str) -> Optional[date]:
        raw = raw.strip().split("~")[0].strip()
        for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except:
                continue
        return None

    def get_course_list(self) -> List[dict]:
        return self._get_courses()

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None
