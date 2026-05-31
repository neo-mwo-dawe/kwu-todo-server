from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from datetime import datetime

from routes.todo import router as todos_router          # 수정: routes.todos → routes.todo
from routes.schedules import router as schedules_router
from routes.auth import router as auth_router          # KLAS 로그인 라우터 (성호 통합)
from state import state                                 # 전역 KLAS 세션


# ────────────────────────────────────────────────
# 앱 생명주기
# ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[START] 서버 시작 - 학사 데이터 초기 로드 중...")
    # TODO: await crawler.run_initial_crawl()
    # TODO: db.init()
    yield
    # 종료 시 SESSION_STORAGE 내 모든 Selenium 드라이버 정리
    try:
        from routes.auth import SESSION_STORAGE
        for sid, user_session in list(SESSION_STORAGE.items()):
            client = user_session.get("klas_client")
            if client:
                try:
                    client.close()
                except Exception:
                    pass
        SESSION_STORAGE.clear()
        print("[STOP] 모든 KLAS 세션 정리 완료")
    except Exception as e:
        print(f"[STOP] 세션 정리 중 오류(무시): {e}")

    state.klas_client = None
    state.is_logged_in = False
    state.student_id = ""
    state.student_name = ""
    print("[STOP] 서버 종료")


# ────────────────────────────────────────────────
# FastAPI 앱 초기화
# ────────────────────────────────────────────────

app = FastAPI(
    title="광운대 학사 TODO API",
    description="학사 일정 크롤링 + LLM 기반 TODO 자동 생성 로컬 서버",
    version="0.1.0",
    lifespan=lifespan,
)

# C# WinForms 앱에서 localhost로 호출하므로 CORS 허용
# 포트 포함/미포함 모두 등록 (Starlette는 origin을 포트까지 포함해 엄격 비교)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ────────────────────────────────────────────────
# 라우터 등록
# ────────────────────────────────────────────────

app.include_router(auth_router)        # /auth/login, /auth/logout, /auth/status
app.include_router(todos_router)       # /todos/*
app.include_router(schedules_router)   # /schedules/*


# ────────────────────────────────────────────────
# 헬스체크
# ────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


# ────────────────────────────────────────────────
# 직접 실행 (WinForms subprocess용)
# ────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )
