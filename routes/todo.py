"""
routes/todo.py
TODO CRUD + AI 자동 생성 엔드포인트
"""

import os
import logging
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, status, Query

from schemas import (
    TodoCreate,
    TodoUpdate,
    TodoResponse,
    GenerateTodoResponse,
    MessageResponse,
)
from database import fake_todos, fake_schedules
from state import state   # KLAS 로그인 세션 공유

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/todos", tags=["TODO"])


# ────────────────────────────────────────────────
# KLAS TodayTask → TodoResponse 변환
# ────────────────────────────────────────────────

def _klas_task_to_response(task) -> TodoResponse:
    """klas_assignment.Task → schemas.TodoResponse"""
    due: Optional[date] = None
    raw_due = getattr(task, "due_date", None)
    if raw_due:
        try:
            due = raw_due if isinstance(raw_due, date) else \
                  datetime.strptime(str(raw_due), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    # klas_assignment.Task 는 days_left(남은 일수)로 긴급도를 표현 → priority 변환
    days_left = getattr(task, "days_left", None)
    if days_left is None:
        priority = "low"
    elif days_left <= 3:
        priority = "high"
    elif days_left <= 7:
        priority = "medium"
    else:
        priority = "low"

    return TodoResponse(
        id=f"klas_{uuid.uuid4().hex[:8]}",
        title=task.title,
        due_date=due,
        priority=priority,
        category=_convert_category(getattr(task, "task_type", "과제")),
        source_event=getattr(task, "course_name", "") or "KLAS",
        is_done=getattr(task, "is_done", False),
        created_at=datetime.now(),
    )


# ────────────────────────────────────────────────
# 내부 변환 헬퍼
# ────────────────────────────────────────────────

def _convert_priority(p: int) -> str:
    """성호's int priority (1=긴급 ~ 4=여유) → schemas.py Literal"""
    if p <= 2:
        return "high"
    if p == 3:
        return "medium"
    return "low"


def _convert_category(cat: str) -> str:
    """성호's category 문자열 → schemas.py Literal"""
    mapping = {
        "학사일정": "학업",
        "LMS과제": "학업",
        "과제": "학업",
        "팀프로젝트": "학업",
        "프로젝트": "학업",
        "온라인강의": "학업",
        "퀴즈": "학업",
        "시험준비": "학업",
        "시험": "학업",
        "수강신청": "행정",
        "행정": "행정",
        "장학": "장학",
        "에브리타임": "기타",
    }
    return mapping.get(cat, "기타")


def _convert_generated_todo(item) -> TodoResponse:
    """todo_generator.TodoItem → schemas.TodoResponse"""
    due: Optional[date] = None
    if item.due_date:
        try:
            if isinstance(item.due_date, date):   # 이미 date 객체
                due = item.due_date
            else:                                  # 문자열 "YYYY-MM-DD"
                due = datetime.strptime(str(item.due_date), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            pass

    created = datetime.now()
    if item.created_at:
        try:
            if isinstance(item.created_at, datetime):
                created = item.created_at
            else:
                created = datetime.fromisoformat(str(item.created_at))
        except Exception:
            pass

    return TodoResponse(
        id=item.id,
        title=item.title,
        due_date=due,
        priority=_convert_priority(item.priority),
        category=_convert_category(item.category),
        source_event=item.source or None,
        is_done=item.completed,
        created_at=created,
    )


# ────────────────────────────────────────────────
# GET /todos/generate  ← /todos/{id} 보다 먼저 선언해야 충돌 없음
# ────────────────────────────────────────────────

@router.get(
    "/generate",
    response_model=GenerateTodoResponse,
    summary="AI TODO 자동 생성",
    description="학사일정 크롤링 + LLM 분석으로 TODO를 생성합니다. API 키 미설정 시 규칙 기반으로 폴백합니다.",
)
def generate_todos(
    period_days: int = Query(30, ge=1, le=180, description="오늘부터 며칠치 일정을 참고할지"),
):
    today = date.today()
    deadline = today + timedelta(days=period_days)

    # ── KLAS 과제/퀴즈 (로그인 상태일 때만) ────────────
    klas_todos: List[TodoResponse] = []
    if state.is_logged_in and state.klas_client is not None:
        try:
            logger.info("[generate_todos] KLAS 크롤링 시작")
            tasks = state.klas_client.collect_all()
            klas_todos = [_klas_task_to_response(t) for t in tasks]
            logger.info(f"[generate_todos] KLAS 과제 {len(klas_todos)}건 수집")
        except Exception as e:
            logger.warning(f"[generate_todos] KLAS 크롤링 실패(무시): {e}")

    # ── LLM 파이프라인 시도 ──────────────────────────
    try:
        from crawler import DataCollector
        from todo_generator import TodoGenerator
        from llm_client import create_llm_client

        # 학사일정 크롤링 (로그인 불필요). KLAS 개인 과제는 위에서 klas_todos로 별도 수집됨.
        collector = DataCollector()
        crawled = collector.collect_all()

        # 크롤링 결과가 비어있으면 fake_schedules를 학사일정으로 사용
        if not crawled.academic_events:
            from crawler import AcademicEvent
            crawled.academic_events = [
                AcademicEvent(
                    title=s["title"],
                    start_date=s["start_date"],
                    end_date=s.get("end_date"),
                    category=s.get("category", ""),
                    source=s.get("source", "kwangwoon"),
                )
                for s in fake_schedules
            ]
            logger.info(f"[generate_todos] 크롤링 결과 없음 -> fake_schedules {len(crawled.academic_events)}개 사용")

        # 오늘 ~ deadline 범위의 다가오는 일정만 (지난 일정 제외)
        crawled.academic_events = [
            e for e in crawled.academic_events
            if today <= e.start_date <= deadline
        ]

        # LLM 클라이언트 초기화 — API 키 없으면 None으로 두고 규칙 기반 생성
        llm_provider = os.getenv("LLM_PROVIDER", "openai")
        try:
            llm_client = create_llm_client(llm_provider)
        except Exception as e:
            logger.info(f"[generate_todos] LLM 비활성(키 없음 등) → 규칙 기반 생성: {e}")
            llm_client = None

        # llm_client=None이면 generate() 내부에서 규칙 기반 폴백으로 처리됨
        generator = TodoGenerator(llm_client=llm_client, use_rule_fallback=True)
        todo_list = generator.generate(crawled)

        todos = [_convert_generated_todo(item) for item in todo_list.sorted_by_priority()]
        # KLAS 과제는 학사일정보다 우선순위 높게 앞에 배치
        todos = klas_todos + todos
        based_on = [e.title for e in crawled.academic_events]

        logger.info(f"[generate_todos] LLM 파이프라인 완료: 학사 {len(todos) - len(klas_todos)}개 + KLAS {len(klas_todos)}개")
        return GenerateTodoResponse(
            todos=todos,
            generated_count=len(todos),
            based_on_schedules=based_on,
        )

    except Exception as e:
        import traceback
        logger.warning(f"[generate_todos] LLM 파이프라인 실패 -> 임시 데이터 사용: {e}")
        logger.debug(traceback.format_exc())

    # ── 최후 폴백: fake_schedules 기반 임시 로직 ────
    target_schedules = [
        s for s in fake_schedules
        if s["start_date"] <= deadline
    ]

    if not target_schedules:
        # 학사일정이 없어도 KLAS 과제는 반환
        return GenerateTodoResponse(
            todos=klas_todos,
            generated_count=len(klas_todos),
            based_on_schedules=[],
        )

    generated_todos: List[TodoResponse] = list(klas_todos)
    for sched in target_schedules:
        todo = TodoResponse(
            id=str(uuid.uuid4()),
            title=f"{sched['title']} 준비하기",
            due_date=sched["start_date"] - timedelta(days=2),
            priority=_priority_from_category(sched["category"]),
            category=_map_category(sched["category"]),
            source_event=sched["title"],
            is_done=False,
            created_at=datetime.now(),
        )
        generated_todos.append(todo)

    return GenerateTodoResponse(
        todos=generated_todos,
        generated_count=len(generated_todos),
        based_on_schedules=[s["title"] for s in target_schedules],
    )


# ────────────────────────────────────────────────
# GET /todos
# ────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[TodoResponse],
    summary="TODO 전체 조회",
)
def get_todos(
    is_done: Optional[bool] = Query(None, description="완료 여부 필터"),
    priority: Optional[str] = Query(None, description="우선순위 필터 (high / medium / low)"),
    category: Optional[str] = Query(None, description="카테고리 필터"),
):
    todos = list(fake_todos.values())

    if is_done is not None:
        todos = [t for t in todos if t["is_done"] == is_done]
    if priority:
        todos = [t for t in todos if t["priority"] == priority]
    if category:
        todos = [t for t in todos if t["category"] == category]

    todos.sort(key=lambda t: (t["due_date"] is None, t["due_date"]))
    return todos


# ────────────────────────────────────────────────
# POST /todos
# ────────────────────────────────────────────────

@router.post(
    "",
    response_model=TodoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="TODO 수동 추가",
)
def create_todo(todo: TodoCreate):
    new_todo = TodoResponse(
        id=str(uuid.uuid4()),
        **todo.model_dump(),
        is_done=False,
        created_at=datetime.now(),
    )
    fake_todos[new_todo.id] = new_todo.model_dump()
    return new_todo


# ────────────────────────────────────────────────
# PUT /todos/{todo_id}
# ────────────────────────────────────────────────

@router.put(
    "/{todo_id}",
    response_model=TodoResponse,
    summary="TODO 수정 (완료 체크 포함)",
)
def update_todo(todo_id: str, update: TodoUpdate):
    if todo_id not in fake_todos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TODO ID '{todo_id}'를 찾을 수 없습니다.",
        )
    stored = fake_todos[todo_id]
    update_data = update.model_dump(exclude_unset=True)
    stored.update(update_data)
    fake_todos[todo_id] = stored
    return stored


# ────────────────────────────────────────────────
# DELETE /todos/{todo_id}
# ────────────────────────────────────────────────

@router.delete(
    "/{todo_id}",
    response_model=MessageResponse,
    summary="TODO 삭제",
)
def delete_todo(todo_id: str):
    if todo_id not in fake_todos:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TODO ID '{todo_id}'를 찾을 수 없습니다.",
        )
    del fake_todos[todo_id]
    return {"message": f"TODO({todo_id}) 삭제 완료"}


# ────────────────────────────────────────────────
# 내부 헬퍼 (폴백 전용)
# ────────────────────────────────────────────────

def _priority_from_category(schedule_category: str) -> str:
    mapping = {"시험": "high", "수강신청": "high", "행사": "medium", "방학": "low", "기타": "medium"}
    return mapping.get(schedule_category, "medium")


def _map_category(schedule_category: str) -> str:
    mapping = {"시험": "학업", "수강신청": "행정", "장학": "장학", "행사": "기타", "방학": "기타", "기타": "기타"}
    return mapping.get(schedule_category, "기타")
