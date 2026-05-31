import uuid
import logging
from datetime import datetime, date, timezone
from typing import List, Optional, Literal

from fastapi import APIRouter, HTTPException, Query

from database import fake_todos
from schemas import (
    TodoCreate, TodoUpdate, TodoResponse,
    GenerateTodoResponse, MessageResponse,
)
from state import state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/todos", tags=["Todos"])


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼
# ──────────────────────────────────────────────────────────────

def _normalize_date_key(value) -> Optional[str]:
    """
    TODO 중복 비교를 위해 date/datetime/str 값을 YYYY-MM-DD 문자열로 통일.
    date 객체와 문자열이 섞여 있어도 같은 날짜면 같은 key로 비교되게 한다.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, str) and value:
        return value[:10]

    return None


def _convert_generated_todo(item: dict) -> TodoResponse:
    """todo_generator.TodoItem.to_api_dict() → TodoResponse 변환"""

    # 1. title 처리
    title = str(item.get("title", "")).strip()
    if not title:
        title = "제목 없음"

    # 2. due_date 처리
    due_date = item.get("due_date")

    if isinstance(due_date, str) and due_date:
        try:
            due_date = date.fromisoformat(due_date[:10])
        except (ValueError, TypeError):
            due_date = None
    elif not isinstance(due_date, date):
        due_date = None

    # 3. category 매핑 표준화
    category_map = {
        "과제": "학업",
        "퀴즈": "학업",
        "온라인강의": "학업",
        "시험": "학업",
        "학업": "학업",

        "학사일정": "행정",
        "수강신청": "행정",
        "행정": "행정",

        "장학": "장학",
        "기타": "기타",
    }

    raw_cat = str(item.get("category", "기타")).strip()
    category = category_map.get(raw_cat, "기타")

    # 4. priority 매핑 및 방어적 코드
    raw_priority = item.get("priority", "medium")

    if isinstance(raw_priority, int):
        priority = {
            1: "high",
            2: "high",
            3: "medium",
            4: "low",
        }.get(raw_priority, "medium")
    else:
        priority = str(raw_priority).strip().lower()
        if priority not in ["high", "medium", "low"]:
            priority = "medium"

    return TodoResponse(
        id=item.get("id") or str(uuid.uuid4()),
        title=title,
        due_date=due_date,
        priority=priority,
        category=category,
        source_event=item.get("source") or item.get("source_event"),
        is_done=item.get("is_completed", False),
        created_at=datetime.now(),  # FIX: timezone.utc 제거 → naive datetime (Python 3.8 SQLite 호환)
    )


def _klas_task_to_response(task) -> TodoResponse:
    """klas_assignment.Task → schemas.TodoResponse 변환"""
    due: Optional[date] = None
    raw_due = getattr(task, "due_date", None)
    if raw_due:
        try:
            due = raw_due if isinstance(raw_due, date) else \
                  datetime.strptime(str(raw_due), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    days_left = getattr(task, "days_left", None)
    if days_left is None:
        priority = "low"
    elif days_left <= 3:
        priority = "high"
    elif days_left <= 7:
        priority = "medium"
    else:
        priority = "low"

    category_map = {
        "과제": "학업", "퀴즈": "학업", "팀프로젝트": "학업",
        "온라인강의": "학업", "시험": "학업",
    }
    raw_cat = getattr(task, "task_type", "기타")
    category = category_map.get(raw_cat, "기타")

    return TodoResponse(
        id=f"klas_{uuid.uuid4().hex[:8]}",
        title=getattr(task, "title", ""),
        due_date=due,
        priority=priority,
        category=category,
        source_event=getattr(task, "course_name", "") or "KLAS",
        is_done=getattr(task, "is_done", False),
        created_at=datetime.now(),
    )


def _make_todo_key(todo: TodoResponse) -> tuple:
    """
    TODO 중복 저장 방지를 위한 비교 키.
    title은 앞뒤 공백 제거, due_date는 YYYY-MM-DD 문자열로 통일한다.
    """
    return (
        todo.title.strip(),
        _normalize_date_key(todo.due_date),
        todo.source_event,
    )


# ──────────────────────────────────────────────────────────────
# GET /todos/generate — AI TODO 자동 생성
# ──────────────────────────────────────────────────────────────

@router.get(
    "/generate",
    response_model=GenerateTodoResponse,
    summary="크롤링 + LLM으로 TODO 자동 생성",
    description=(
        "광운대 학사일정 크롤링 후 LLM으로 TODO를 생성합니다.\n"
        "KLAS 로그인 상태이면 과제/강의 정보도 포함합니다.\n"
        "OpenAI 쿼터 초과 또는 키 없을 경우 규칙 기반으로 폴백합니다."
    ),
)
def generate_todos(
    provider: Literal["claude", "openai"] = Query(
        "claude",
        description="LLM 제공자: claude | openai",
    ),
    refine: bool = Query(
        False,
        description="우선순위 재검토 여부 (느림)",
    ),
):
    from crawler import DataCollector
    from todo_generator import run_pipeline
    from database import fake_schedules as _fake_schedules

    # 1. KLAS 로그인 상태이면 KLASCrawler.collect_all()로 과제 직접 수집
    #    (klas_assignment.py 크롤러 — get_assignments/get_projects/get_online_lectures)
    klas_todos: List[TodoResponse] = []
    if state.is_logged_in and state.klas_client:
        try:
            logger.info("[generate] KLAS 과제 직접 수집 시작")
            tasks = state.klas_client.collect_all()
            klas_todos = [_klas_task_to_response(t) for t in tasks]
            logger.info(f"[generate] KLAS 과제 {len(klas_todos)}건 수집")
        except Exception as e:
            logger.warning(f"[generate] KLAS 직접 수집 실패(무시): {e}")

    # 2. DataCollector로 학사일정 + KLAS 크롤링
    #    (klas_driver 전달 시 crawler.py의 KlasAssignmentCrawler도 실행)
    klas_driver = (
        state.klas_client.driver
        if state.klas_client and state.is_logged_in
        else None
    )
    collector = DataCollector(klas_driver=klas_driver)
    data = collector.collect_all()

    # 3. 크롤링 결과가 비면 fallback 학사일정 주입
    if not data.academic_events:
        logger.warning("[generate] 크롤링 결과 없음 — fake_schedules 주입")

        from crawler import AcademicEvent

        for s in _fake_schedules:
            data.academic_events.append(
                AcademicEvent(
                    title=s["title"],
                    start_date=s["start_date"],
                    end_date=s.get("end_date"),
                    category=s.get("category", "기타"),
                )
            )

    # 4. TODO 생성 Pipeline 실행
    try:
        todo_list = run_pipeline(
            data,
            llm_provider=provider,
            refine=refine,
        )
    except Exception as e:
        logger.error(f"[generate] run_pipeline 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"TODO 생성 실패: {e}",
        )

    # 5. 응답 변환 (KLAS 직접 수집 + LLM 생성 합산)
    api_data = todo_list.to_api_response()
    llm_todos = [_convert_generated_todo(t) for t in api_data["todos"]]
    all_todos = klas_todos + llm_todos  # KLAS 과제를 앞에 배치 (우선순위 높음)

    # 6. 중복 방지 후 DB 저장
    existing_keys = {
        (
            str(t.get("title", "")).strip(),
            _normalize_date_key(t.get("due_date")),
            t.get("source_event"),
        )
        for t in fake_todos.values()
    }

    saved_todos = []
    for todo in all_todos:
        todo_key = _make_todo_key(todo)
        if todo_key in existing_keys:
            continue
        fake_todos[todo.id] = todo.model_dump()
        existing_keys.add(todo_key)
        saved_todos.append(todo)

    return GenerateTodoResponse(
        todos=saved_todos,
        generated_count=len(saved_todos),
        based_on_schedules=[e.title for e in data.academic_events[:10]],
    )


# ──────────────────────────────────────────────────────────────
# GET /todos — 전체 조회
# ──────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[TodoResponse],
    summary="저장된 TODO 전체 조회",
)
def get_todos(
    is_done: Optional[bool] = Query(
        None,
        description="완료 여부 필터 (생략 시 전체)",
    ),
    category: Optional[str] = Query(
        None,
        description="카테고리 필터",
    ),
):
    filtered_todos = []

    for t in fake_todos.values():
        if is_done is not None and t.get("is_done") != is_done:
            continue
        if category and t.get("category") != category:
            continue
        filtered_todos.append(TodoResponse(**t))

    return filtered_todos


# ──────────────────────────────────────────────────────────────
# POST /todos — 수동 추가
# ──────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=TodoResponse,
    status_code=201,
    summary="TODO 수동 추가",
)
def create_todo(body: TodoCreate):
    new_id = str(uuid.uuid4())

    todo_data = {
        **body.model_dump(),
        "id": new_id,
        "is_done": False,
        "created_at": datetime.now(),  # FIX: naive datetime (SQLite 호환)
    }

    fake_todos[new_id] = todo_data
    return TodoResponse(**todo_data)


# ──────────────────────────────────────────────────────────────
# PUT /todos/{id} — 수정
# ──────────────────────────────────────────────────────────────

@router.put(
    "/{todo_id}",
    response_model=TodoResponse,
    summary="TODO 수정 (완료 처리 포함)",
)
def update_todo(todo_id: str, body: TodoUpdate):
    if todo_id not in fake_todos:
        raise HTTPException(
            status_code=404,
            detail=f"TODO를 찾을 수 없습니다: {todo_id}",
        )

    existing = fake_todos[todo_id]
    updates = body.model_dump(exclude_unset=True)
    existing.update(updates)
    fake_todos[todo_id] = existing

    return TodoResponse(**existing)


# ──────────────────────────────────────────────────────────────
# DELETE /todos/{id} — 삭제
# ──────────────────────────────────────────────────────────────

@router.delete(
    "/{todo_id}",
    response_model=MessageResponse,
    summary="TODO 삭제",
)
def delete_todo(todo_id: str):
    if todo_id not in fake_todos:
        raise HTTPException(
            status_code=404,
            detail=f"TODO를 찾을 수 없습니다: {todo_id}",
        )

    del fake_todos[todo_id]
    return MessageResponse(message=f"TODO {todo_id} 삭제 완료")
