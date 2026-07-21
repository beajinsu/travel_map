"""비행 제외 설정과 승인된 자동 탐지 후보를 공통 형식으로 읽는다."""

import json
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_EXCLUSIONS_PATH = SCRIPT_DIR / "flight_exclusions.json"
DEFAULT_CANDIDATES_PATH = SCRIPT_DIR / "flight_candidates.json"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class FlightSettingsError(ValueError):
    """비행 설정 파일의 형식이 잘못되었을 때 발생한다."""


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FlightSettingsError(
            f"{path.name} JSON 형식 오류: {exc.msg} (줄 {exc.lineno})"
        ) from exc


def _number(value, field, source):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FlightSettingsError(f"{source}: {field} 값은 숫자여야 합니다.")
    if value < 0:
        raise FlightSettingsError(f"{source}: {field} 값은 0 이상이어야 합니다.")
    return float(value)


def _parse_period(raw, source, default_before=0.0, default_after=0.0):
    if not isinstance(raw, dict):
        raise FlightSettingsError(f"{source}: 각 비행 구간은 JSON 객체여야 합니다.")

    name = str(raw.get("name") or raw.get("id") or source).strip()
    start_text = str(raw.get("start", "")).strip()
    end_text = str(raw.get("end", "")).strip()

    try:
        start = datetime.strptime(start_text, TIME_FORMAT)
        end = datetime.strptime(end_text, TIME_FORMAT)
    except ValueError as exc:
        raise FlightSettingsError(
            f"{source}: start/end는 YYYY-MM-DD HH:MM:SS 형식이어야 합니다."
        ) from exc

    if end < start:
        raise FlightSettingsError(f"{source}: end가 start보다 빠릅니다.")

    before = _number(
        raw.get("buffer_before_hours", default_before),
        "buffer_before_hours",
        source,
    )
    after = _number(
        raw.get("buffer_after_hours", default_after),
        "buffer_after_hours",
        source,
    )

    return {
        "id": str(raw.get("id") or "").strip(),
        "name": name,
        "start": start,
        "end": end,
        "buffer_before_hours": before,
        "buffer_after_hours": after,
        "effective_start": start - timedelta(hours=before),
        "effective_end": end + timedelta(hours=after),
        "source": source,
    }


def load_flight_periods(
    exclusions_path=DEFAULT_EXCLUSIONS_PATH,
    candidates_path=DEFAULT_CANDIDATES_PATH,
):
    """활성 수동 구간과 approved=true인 후보 구간을 함께 반환한다."""
    exclusions_path = Path(exclusions_path)
    candidates_path = Path(candidates_path)
    periods = []
    counts = {"manual": 0, "approved_candidates": 0}

    if exclusions_path.exists():
        settings = _load_json(exclusions_path)
        if not isinstance(settings, dict):
            raise FlightSettingsError(
                f"{exclusions_path.name}: 최상위 값은 JSON 객체여야 합니다."
            )

        defaults = settings.get("defaults", {})
        if not isinstance(defaults, dict):
            raise FlightSettingsError(
                f"{exclusions_path.name}: defaults는 JSON 객체여야 합니다."
            )
        default_before = _number(
            defaults.get("buffer_before_hours", 0),
            "defaults.buffer_before_hours",
            exclusions_path.name,
        )
        default_after = _number(
            defaults.get("buffer_after_hours", 0),
            "defaults.buffer_after_hours",
            exclusions_path.name,
        )

        raw_periods = settings.get("periods", [])
        if not isinstance(raw_periods, list):
            raise FlightSettingsError(
                f"{exclusions_path.name}: periods는 JSON 배열이어야 합니다."
            )

        for index, raw in enumerate(raw_periods, start=1):
            if isinstance(raw, dict) and raw.get("enabled", True) is False:
                continue
            periods.append(
                _parse_period(
                    raw,
                    f"{exclusions_path.name} periods[{index}]",
                    default_before,
                    default_after,
                )
            )
            counts["manual"] += 1

    if candidates_path.exists():
        candidates = _load_json(candidates_path)
        if not isinstance(candidates, dict):
            raise FlightSettingsError(
                f"{candidates_path.name}: 최상위 값은 JSON 객체여야 합니다."
            )
        raw_groups = candidates.get("candidate_groups", [])
        if not isinstance(raw_groups, list):
            raise FlightSettingsError(
                f"{candidates_path.name}: candidate_groups는 JSON 배열이어야 합니다."
            )

        for index, raw in enumerate(raw_groups, start=1):
            if not isinstance(raw, dict) or raw.get("approved") is not True:
                continue
            candidate = dict(raw)
            candidate.setdefault("name", candidate.get("id") or f"승인 후보 {index}")
            candidate.setdefault("buffer_before_hours", 0)
            candidate.setdefault("buffer_after_hours", 0)
            periods.append(
                _parse_period(
                    candidate,
                    f"{candidates_path.name} candidate_groups[{index}]",
                )
            )
            counts["approved_candidates"] += 1

    periods.sort(key=lambda period: (period["effective_start"], period["name"]))
    return periods, counts


def match_flight(photo_time, periods):
    """촬영 시간이 제외 구간이면 해당 구간을, 아니면 None을 반환한다."""
    if photo_time is None:
        return None
    if photo_time.tzinfo is not None:
        photo_time = photo_time.replace(tzinfo=None)
    for period in periods:
        if period["effective_start"] <= photo_time <= period["effective_end"]:
            return period
    return None


def period_summary(period):
    start = period["start"].strftime(TIME_FORMAT)
    end = period["end"].strftime(TIME_FORMAT)
    before = period["buffer_before_hours"]
    after = period["buffer_after_hours"]
    return f"{period['name']}: {start} ~ {end} (버퍼 -{before:g}h/+{after:g}h)"
