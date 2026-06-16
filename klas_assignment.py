"""
klas_assignment.py
KLAS 로그인 후 수강과목별 정보 수집 (과제 / 팀프로젝트 / 온라인강의)

수집 방식: KLAS 내부 JSON API 직접 호출
  · 과목 목록   : 대시보드 Vue 앱(appModule.atnlcSbjectList)에서 추출
  · 과제        : POST /std/lis/evltn/TaskStdList.do
  · 팀프로젝트  : POST /std/lis/evltn/PrjctStdList.do
  · 온라인강의  : POST /std/lis/evltn/SelectOnlineCntntsStdList.do

이전에는 각 페이지의 DOM 을 BeautifulSoup 으로 긁었으나, KLAS 가 SPA 라
비동기 렌더링 타이밍/구조 차이로 특히 팀프로젝트가 자주 0건으로 누락됐다.
API 를 직접 호출하면 제출여부·마감일이 JSON 으로 정확히 들어와 누락이 없다.

API 방식·엔드포인트 출처: KLAS Helper (MIT License, © 2020-2021 nbsp1221)
  https://github.com/nbsp1221/klas-helper

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
# KLAS 크롤러 (JSON API 방식)
# ──────────────────────────────────────────────

class KLASCrawler:

    LOGIN_URL     = f"{BASE_URL}/usr/cmn/login/LoginForm.do"
    DASHBOARD_URL = f"{BASE_URL}/std/cmn/frame/Frame.do"

    # KLAS 내부 JSON API (출처: KLAS Helper, MIT © nbsp1221)
    #   body = {selectSubj, selectYearhakgi, selectChangeYn:'Y'}
    TASK_API    = "/std/lis/evltn/TaskStdList.do"               # 과제
    PROJECT_API = "/std/lis/evltn/PrjctStdList.do"              # 팀프로젝트
    ONLINE_API  = "/std/lis/evltn/SelectOnlineCntntsStdList.do"  # 온라인강의

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
        self.driver.set_script_timeout(30)   # execute_async_script(fetch) 대기 시간
        self.wait      = WebDriverWait(self.driver, 15)
        self.logged_in = False
        self._logged_keys = set()             # API 응답 필드명 1회 로깅용 (필드 확인/디버깅)

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
        if not raw or str(raw).strip() == "":
            return None, "마감일 미정", None

        raw = str(raw).strip()
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

    # ── 수강과목 목록 (대시보드 Vue 데이터) ──────

    def _get_subjects(self) -> List[dict]:
        """
        대시보드 프레임에서 수강과목 목록을 추출한다.
        KLAS Helper 가 사용하는 appModule.atnlcSbjectList 를 읽는다.
        각 항목: {subj(과목코드), subjNm(과목명), yearhakgi(년학기)}
        """
        self.driver.get(self.DASHBOARD_URL)
        time.sleep(2.5)

        subjects = None
        exprs = [
            "return (typeof appModule !== 'undefined' && appModule.atnlcSbjectList) ? appModule.atnlcSbjectList : null;",
            "return (typeof appModule !== 'undefined' && appModule.$data && appModule.$data.atnlcSbjectList) ? appModule.$data.atnlcSbjectList : null;",
        ]
        for expr in exprs:
            try:
                subjects = self.driver.execute_script(expr)
            except Exception:
                subjects = None
            if subjects:
                break

        result = []
        if subjects:
            for s in subjects:
                subj = s.get("subj") or s.get("subjCd") or s.get("subject")
                yh   = s.get("yearhakgi") or s.get("yearHakgi") or s.get("yearhakgiCd")
                nm   = s.get("subjNm") or s.get("subjectNm") or s.get("subjectName") or ""
                if subj and yh:
                    result.append({"subj": subj, "yearhakgi": yh, "name": nm or subj})
        else:
            logger.warning("[KLAS] 대시보드에서 수강과목 목록을 찾지 못함 (appModule.atnlcSbjectList 없음)")

        return result

    # ── KLAS JSON API 호출 (브라우저 세션 컨텍스트) ─

    def _api_post(self, endpoint: str, subj: str, yearhakgi: str) -> list:
        """
        로그인된 브라우저 세션에서 KLAS JSON API 를 POST 호출한다.
        같은 출처(same-origin) fetch 라 세션 쿠키가 자동 전송된다.
        """
        body = json.dumps({
            "selectSubj": subj,
            "selectYearhakgi": yearhakgi,
            "selectChangeYn": "Y",
        })
        script = """
            const cb = arguments[arguments.length - 1];
            fetch(arguments[0], {
                method: 'POST',
                headers: {'Content-Type': 'application/json;charset=UTF-8'},
                body: arguments[1],
                credentials: 'same-origin'
            })
            .then(r => r.json())
            .then(d => cb(d))
            .catch(e => cb({__error: String(e)}));
        """
        try:
            data = self.driver.execute_async_script(script, endpoint, body)
        except Exception as e:
            logger.warning(f"[API] {endpoint} 호출 실패: {e}")
            return []

        if isinstance(data, dict) and data.get("__error"):
            logger.warning(f"[API] {endpoint} 응답 오류: {data['__error']}")
            return []
        return data if isinstance(data, list) else []

    def _log_keys(self, tag: str, items: list):
        """API 응답 첫 항목의 필드명을 1회만 로깅 (필드 확인용)"""
        if tag not in self._logged_keys and isinstance(items, list) and items:
            logger.info(f"[API:{tag}] 응답 필드: {list(items[0].keys())}")
            self._logged_keys.add(tag)

    def _pick_title(self, item: dict) -> str:
        """JSON 항목에서 제목으로 쓸 값을 골라낸다 (필드명이 항목별로 달라 후보 순회)"""
        for k in ("title", "moduletitle", "moduleTitle", "lesson", "sbjt",
                  "rpttitle", "rptTitle", "subject", "prjtitle",
                  "prjctNm", "prjctTitle", "cntntsNm", "lessonNm", "evltnNm",
                  "name", "rptNm", "homeworkTitle"):
            v = item.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return "(제목 미확인)"

    # ── 과제/팀프로젝트 파싱 ─────────────────────

    def _parse_homework_items(self, items: list, course_name: str, task_type: str) -> List[Task]:
        """과제/팀프로젝트 JSON 파싱 (제출 완료·마감 지난 항목 제외)"""
        tasks = []
        for hw in items:
            if str(hw.get("submityn", "")).upper() == "Y":
                continue

            due_date, due_str, days_left = self._parse_due(hw.get("expiredate", ""))

            # 마감 지났으면 추가 제출 기한 확인
            if days_left is not None and days_left < 0:
                re_raw = hw.get("reexpiredate", "")
                if not re_raw:
                    continue
                due_date, due_str, days_left = self._parse_due(re_raw)
                if days_left is not None and days_left < 0:
                    continue

            title = self._pick_title(hw)
            tasks.append(Task(task_type, course_name, title, due_str, due_date, False, days_left))
        return tasks

    # ── 온라인강의 파싱 ──────────────────────────

    def _parse_lecture_items(self, items: list, course_name: str) -> List[Task]:
        """온라인강의 JSON 파싱 (진도 100% 아님 & 마감 안 지난 미수강분만)"""
        tasks = []
        for lec in items:
            if lec.get("evltnSe") and lec.get("evltnSe") != "lesson":
                continue
            try:
                if float(lec.get("prog", 0)) >= 100:
                    continue
            except (TypeError, ValueError):
                pass

            due_date, due_str, days_left = self._parse_due(lec.get("endDate", ""))
            if days_left is not None and days_left < 0:
                continue

            title = self._pick_title(lec)
            tasks.append(Task("온라인강의", course_name, title, due_str, due_date, False, days_left))
        return tasks

    # ── 전체 수집 ────────────────────────────────

    def collect_all(self) -> List[Task]:
        if not self.logged_in:
            logger.warning("[KLAS] 미로그인 상태 — 수집 중단")
            return []

        subjects = self._get_subjects()
        logger.info(f"[KLAS] 수강과목 {len(subjects)}개")

        all_tasks: List[Task] = []
        for s in subjects:
            subj, yh, name = s["subj"], s["yearhakgi"], s["name"]

            # 과제
            items = self._api_post(self.TASK_API, subj, yh)
            self._log_keys("Task", items)
            hw = self._parse_homework_items(items, name, "과제")
            # 제목에 Project/프로젝트 포함 시 프로젝트로 재분류 (기존 동작 유지)
            for t in hw:
                if any(k in t.title for k in ["Project", "프로젝트"]):
                    t.task_type = "프로젝트"
            all_tasks.extend(hw)

            # 팀프로젝트
            items = self._api_post(self.PROJECT_API, subj, yh)
            self._log_keys("Prjct", items)
            all_tasks.extend(self._parse_homework_items(items, name, "팀프로젝트"))

            # 온라인강의
            items = self._api_post(self.ONLINE_API, subj, yh)
            self._log_keys("Online", items)
            all_tasks.extend(self._parse_lecture_items(items, name))

            logger.info(f"  [{name}] 누적 {len(all_tasks)}건")

        # 중복 제거
        seen, unique = set(), []
        for t in all_tasks:
            key = f"{t.course_name}_{t.task_type}_{t.title}"
            if key not in seen:
                seen.add(key)
                unique.append(t)

        logger.info(f"[KLAS] 총 {len(unique)}건 수집 (JSON API)")
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
