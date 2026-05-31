"""
routes/schedules.py
학사일정 조회 엔드포인트

엔드포인트:
  GET /schedules          — 학사일정 전체/필터 조회
  GET /schedules/refresh  — 크롤러 재실행 후 최신 일정 반환
"""

import logging
import uuid
from datetime import date, datetime
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException
from fastapi.concurrency import run_in_threadpool

from database import fake_schedules
from schemas import ScheduleResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["Schedules"])

ALLOWED_CATEGORIES = ("시험", "수강신청", "방학", "행사", "기타")


# ──────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ──────────────────────────────────────────────────────────────

def _parse_date(value) -> Optional[date]:
    """date 또는 다양한 포맷의 문자열 날짜를 date 타입으로 변환"""
    if value is None:
        return None

    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    for fmt in ["%Y.%m.%d", "%Y/%m/%d"]:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def _normalize_schedule_dates(schedule: dict) -> dict:
    """스케줄의 start_date, end_date를 date 타입으로 정리"""
    copied = dict(schedule)
    copied["start_date"] = _parse_date(copied.get("start_date"))
    # FIX: end_date는 Optional[date] — None 그대로 유지 (start_date로 강제 채우지 않음)
    copied["end_date"] = _parse_date(copied.get("end_date"))
    return copied


def _normalize_category(category: str) -> str:
    """허용된 카테고리만 반환하고, 그 외 값은 기타로 처리"""
    return category if category in ALLOWED_CATEGORIES else "기타"


def _crawl_academic_calendar(days_ahead: int):
    """동기 크롤링 함수"""
    from crawler import AcademicCalendarCrawler

    crawler = AcademicCalendarCrawler()
    return crawler.crawl(days_ahead=days_ahead)


def _fetch_and_filter_cached_schedules(
    category: Optional[str] = None,
    upcoming: bool = False,
) -> List[ScheduleResponse]:
    """데이터베이스(캐시)에서 스케줄을 조회하고 필터링하는 공통 비즈니스 로직"""
    schedules = [_normalize_schedule_dates(s) for s in fake_schedules]

    if category:
        category = category.strip()

        if category not in ALLOWED_CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=f"허용되지 않는 카테고리입니다. 사용 가능: {', '.join(ALLOWED_CATEGORIES)}",
            )

        schedules = [s for s in schedules if s.get("category") == category]

    if upcoming:
        today = date.today()
        # end_date가 None인 항목은 start_date 기준으로 비교
        schedules = [
            s for s in schedules
            if (s.get("end_date") or s.get("start_date")) >= today
        ]

    result = []

    for s in schedules:
        if not s.get("id"):
            s = {**s, "id": str(uuid.uuid4())}

        if not s.get("start_date"):
            logger.warning(f"[schedules] 시작일이 없어 제외됨 ({s.get('title')})")
            continue

        try:
            result.append(ScheduleResponse(**s))
        except Exception as e:
            logger.warning(f"[schedules] 스키마 변환 실패 ({s.get('title')}): {e}")

    return result


# ──────────────────────────────────────────────────────────────
# GET /schedules — 학사일정 조회
# ──────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=List[ScheduleResponse],
    summary="학사일정 조회",
    description="저장된 학사일정 목록을 반환합니다. category, upcoming 필터를 사용할 수 있습니다.",
)
def get_schedules(
    category: Optional[str] = Query(
        None,
        description="카테고리 필터 (시험 | 수강신청 | 방학 | 행사 | 기타)",
    ),
    upcoming: bool = Query(
        False,
        description="True이면 오늘 이후 일정만 반환",
    ),
):
    return _fetch_and_filter_cached_schedules(
        category=category,
        upcoming=upcoming,
    )


# ──────────────────────────────────────────────────────────────
# GET /schedules/refresh — 크롤러 재실행 후 최신 일정 반환
# ──────────────────────────────────────────────────────────────

@router.get(
    "/refresh",
    response_model=List[ScheduleResponse],
    summary="학사일정 크롤러 재실행",
    description="광운대 학사일정 페이지를 직접 크롤링해 최신 데이터를 반환합니다. 실패 시 캐시 데이터를 반환합니다.",
)
async def refresh_schedules(
    days_ahead: int = Query(
        90,
        ge=1,
        le=365,
        description="오늘로부터 며칠치 일정을 가져올지",
    ),
):
    try:
        events = await run_in_threadpool(_crawl_academic_calendar, days_ahead)
        logger.info(f"[schedules/refresh] {len(events)}건 수집")

    except Exception as e:
        logger.error(f"[schedules/refresh] 크롤링 실패 — 캐시 반환: {e}")
        return _fetch_and_filter_cached_schedules()

    if not events:
        logger.warning("[schedules/refresh] 크롤링 결과 없음 — 캐시 반환")
        return _fetch_and_filter_cached_schedules()

    result = []

    for ev in events:
        try:
            title = getattr(ev, "title", "")
            start_date = _parse_date(getattr(ev, "start_date", None))

            if not start_date:
                logger.warning(f"[schedules/refresh] 시작일이 없어 제외됨 ({title})")
                continue

            # FIX: end_date는 Optional[date] — None 그대로 유지
            end_date = _parse_date(getattr(ev, "end_date", None))

            result.append(
                ScheduleResponse(
                    id=str(uuid.uuid4()),
                    title=title,
                    start_date=start_date,
                    end_date=end_date,
                    category=_normalize_category(getattr(ev, "category", "")),
                    source=getattr(ev, "source", "") or "https://www.kw.ac.kr",
                )
            )

        except Exception as e:
            title = getattr(ev, "title", "")
            logger.warning(f"[schedules/refresh] 스키마 변환 실패 ({title}): {e}")

    return result


# ──────────────────────────────────────────────────────────────
# GET /schedules/{schedule_id} — 단건 조회
# /refresh보다 뒤에 선언해야 "refresh"가 {schedule_id}로 잡히지 않음
# ──────────────────────────────────────────────────────────────

@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="특정 학사일정 단건 조회",
)
def get_schedule(schedule_id: str):
    target = next(
        (s for s in fake_schedules if s.get("id") == schedule_id),
        None,
    )
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"학사일정 ID '{schedule_id}'를 찾을 수 없습니다.",
        )
    return ScheduleResponse(**_normalize_schedule_dates(target))
