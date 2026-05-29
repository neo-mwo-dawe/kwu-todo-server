"""
state.py — 글로벌 앱 상태 (KLAS 로그인 세션)

여러 라우터(auth, todo)에서 공유해야 하는 KLAS 클라이언트와
로그인 정보를 한 곳에 모아둔다. 서버 재시작 시 초기화됨.

수동 TODO는 SQLite(database.py)에서 영속화되므로 여기에 두지 않음.
"""

from typing import Optional
from klas_crawler import KLASClient


class AppState:
    """KLAS 로그인 세션 상태 (단일 사용자 가정 — 로컬 데스크탑 앱)"""
    klas_client: Optional[KLASClient] = None
    student_id: str = ""
    student_name: str = ""
    is_logged_in: bool = False


# 모든 라우터에서 from state import state 로 import
state = AppState()
