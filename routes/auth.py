"""
routes/auth.py — KLAS 로그인/로그아웃/상태 엔드포인트

광운대 학사관리시스템(KLAS)에 실제로 로그인하여 세션을 유지한다.
로그인 후 state.klas_client 를 통해 다른 라우터에서 KLAS 데이터를 조회 가능.
"""

import logging
from fastapi import APIRouter

from klas_crawler import KLASClient
from schemas import LoginRequest, LoginResponse, AuthStatusResponse
from state import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse, summary="KLAS 로그인")
def login(req: LoginRequest):
    """
    학번/비밀번호로 광운대 KLAS 에 실제 로그인한다.
    성공 시 KLAS 세션을 서버 메모리에 저장 → 이후 /todos/generate 호출 시 사용.

    C# LoginForm 에서 호출.
    """
    logger.info(f"[API] 로그인 요청: {req.student_id}")

    # 기존 세션 정리 (계정 전환 대비)
    if state.klas_client:
        try:
            state.klas_client.close()
        except Exception as e:
            logger.warning(f"[API] 기존 세션 정리 실패(무시): {e}")
        state.klas_client = None

    client = KLASClient()
    result = client.login(req.student_id, req.password)

    if result.get("success"):
        state.klas_client = client
        state.student_id = req.student_id
        state.is_logged_in = True

        student = result["student"]
        state.student_name = student.name or req.student_id

        return LoginResponse(
            success=True,
            message="로그인 성공",
            student_name=state.student_name,
            student_id=req.student_id,
            semester=getattr(student, "semester", "") or "",
        )

    return LoginResponse(
        success=False,
        message=result.get("message", "로그인 실패"),
    )


@router.post("/logout", summary="KLAS 로그아웃")
def logout():
    """KLAS 세션 정리. 클라이언트는 자체적으로 LoginForm 으로 복귀."""
    if state.klas_client:
        try:
            state.klas_client.close()
        except Exception as e:
            logger.warning(f"[API] 로그아웃 중 오류(무시): {e}")
        state.klas_client = None

    state.is_logged_in = False
    state.student_id = ""
    state.student_name = ""
    return {"success": True, "message": "로그아웃 완료"}


@router.get("/status", response_model=AuthStatusResponse, summary="로그인 상태 확인")
def auth_status():
    """현재 KLAS 로그인 상태를 반환. C# 앱이 시작 시 호출하여 자동 복원 가능."""
    return AuthStatusResponse(
        logged_in=state.is_logged_in,
        student_id=state.student_id,
        student_name=state.student_name,
    )
