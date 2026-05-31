import logging
import asyncio
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict

from fastapi import APIRouter, HTTPException, Cookie, Response

from klas_assignment import KLASCrawler
from schemas import LoginRequest, LoginResponse, AuthStatusResponse
from state import state  # A안: todo.py와 공유하는 전역 상태 병행 유지

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])

# Selenium 블로킹 I/O용 스레드 풀
executor = ThreadPoolExecutor(max_workers=10)

# 인메모리 세션 저장소
SESSION_STORAGE: Dict[str, dict] = {}

# 세션 만료 시간: 30분
SESSION_TTL_SECONDS = 60 * 30


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────

def _is_session_expired(user_session: dict) -> bool:
    return time.time() - user_session.get("last_accessed_at", 0) > SESSION_TTL_SECONDS


def _remove_session(session_id: str):
    """세션 삭제 + Selenium 드라이버 종료 + state 초기화"""
    user_session = SESSION_STORAGE.pop(session_id, None)
    if not user_session:
        return

    client = user_session.get("klas_client")
    if client:
        try:
            client.close()  # KLASCrawler.close() → self.driver.quit()
        except Exception:
            pass

    # A안: state도 함께 초기화
    state.klas_client = None
    state.is_logged_in = False
    state.student_id = ""
    state.student_name = ""


def _run_selenium_login(body: LoginRequest):
    """스레드 풀에서 실행될 동기 Selenium 로그인 로직"""
    client = None
    try:
        client = KLASCrawler(headless=True)
        success = client.login(body.student_id, body.password)

        if not success:
            client.close()  # FIX: quit() → close() (KLASCrawler 메서드)
            return None, "학번 또는 비밀번호가 올바르지 않습니다."

        # 학생 이름 추출 시도
        name = ""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(client.driver.page_source, "html.parser")
            for sel in [".user-name", ".mypage-name", "#userName", ".name"]:
                tag = soup.select_one(sel)
                if tag:
                    name = tag.get_text(strip=True)
                    break
        except Exception:
            pass

        # 이름 미추출 시 학번으로 대체
        if not name:
            name = body.student_id

        return {"client": client, "name": name}, None

    except Exception as e:
        if client:
            try:
                client.close()  # FIX: quit() → close()
            except Exception:
                pass
        return None, str(e)


# ──────────────────────────────────────────────────────────────
# POST /auth/login
# ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse, summary="KLAS 로그인")
async def login(body: LoginRequest, response: Response, session_id: str = Cookie(None)):
    # 1. 기존 세션 재사용 or 만료 처리
    if session_id and session_id in SESSION_STORAGE:
        user_session = SESSION_STORAGE[session_id]

        if _is_session_expired(user_session):
            logger.info(f"[auth/login] 만료 세션 삭제: {session_id}")
            _remove_session(session_id)
            response.delete_cookie(key="session_id")
        else:
            user_session["last_accessed_at"] = time.time()
            logger.info(f"[auth/login] 기존 세션 재사용: {body.student_id}")
            return LoginResponse(
                success=True,
                message="이미 로그인 상태입니다.",
                student_id=user_session["student_id"],
                student_name=user_session["student_name"],
            )

    # 2. 같은 학번의 이전 세션이 남아있으면 드라이버 누수 방지를 위해 먼저 정리
    #    FIX: 고정 session_id(f"session_{student_id}") 대신 UUID 사용
    stale_ids = [
        sid for sid, s in SESSION_STORAGE.items()
        if s.get("student_id") == body.student_id
    ]
    for stale_id in stale_ids:
        logger.info(f"[auth/login] 이전 세션 정리: {stale_id}")
        _remove_session(stale_id)

    # 3. Selenium 로그인 (스레드 풀 — 서버 블로킹 방지)
    loop = asyncio.get_running_loop()
    result, error_msg = await loop.run_in_executor(executor, _run_selenium_login, body)

    if error_msg:
        logger.error(f"[auth/login] 로그인 실패: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    # 4. 세션 생성 (FIX: UUID로 고유 session_id 생성)
    new_session_id = str(uuid.uuid4())
    now = time.time()

    SESSION_STORAGE[new_session_id] = {
        "klas_client": result["client"],
        "student_id": body.student_id,
        "student_name": result["name"],
        "created_at": now,
        "last_accessed_at": now,
    }

    # A안: state도 함께 업데이트 → todo.py가 state로 KLAS 접근 가능
    state.klas_client = result["client"]
    state.student_id = body.student_id
    state.student_name = result["name"]
    state.is_logged_in = True

    response.set_cookie(key="session_id", value=new_session_id, httponly=True)
    logger.info(f"[auth/login] 로그인 성공: {body.student_id}")

    return LoginResponse(
        success=True,
        message="로그인 성공",
        student_id=body.student_id,
        student_name=result["name"],
    )


# ──────────────────────────────────────────────────────────────
# POST /auth/logout
# ──────────────────────────────────────────────────────────────

@router.post("/logout", summary="KLAS 로그아웃")
async def logout(response: Response, session_id: str = Cookie(None)):
    if not session_id or session_id not in SESSION_STORAGE:
        return {"message": "로그인 상태가 아닙니다."}

    user_session = SESSION_STORAGE[session_id]
    client = user_session.get("klas_client")

    if client:
        try:
            # FIX: quit() → close(), 스레드 풀에서 비동기 처리
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(executor, client.close)
            logger.info(f"[auth/logout] KLAS 드라이버 종료: {user_session['student_id']}")
        except Exception as e:
            logger.warning(f"[auth/logout] 드라이버 종료 중 오류(무시): {e}")

    SESSION_STORAGE.pop(session_id, None)

    # A안: state 초기화
    state.klas_client = None
    state.is_logged_in = False
    state.student_id = ""
    state.student_name = ""

    response.delete_cookie(key="session_id")
    return {"message": "로그아웃 완료"}


# ──────────────────────────────────────────────────────────────
# GET /auth/status
# ──────────────────────────────────────────────────────────────

@router.get("/status", response_model=AuthStatusResponse, summary="KLAS 로그인 상태 확인")
async def auth_status(response: Response, session_id: str = Cookie(None)):
    if not session_id or session_id not in SESSION_STORAGE:
        return AuthStatusResponse(logged_in=False, student_id="", student_name="")

    user_session = SESSION_STORAGE[session_id]

    if _is_session_expired(user_session):
        logger.info(f"[auth/status] 만료 세션 삭제: {session_id}")
        _remove_session(session_id)  # A안: state도 함께 초기화
        response.delete_cookie(key="session_id")
        return AuthStatusResponse(logged_in=False, student_id="", student_name="")

    user_session["last_accessed_at"] = time.time()

    return AuthStatusResponse(
        logged_in=True,
        student_id=user_session["student_id"],
        student_name=user_session["student_name"],
    )
