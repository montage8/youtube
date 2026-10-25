"""보이스오버가 읽기 쉬운 한국어 문구를 만드는 순수 함수 모음.

시각장애 사용자는 "10:23" 같은 숫자보다 "10분 23초"를 훨씬 빨리 이해합니다.
모든 표 행에는 화면용 짧은 문자열과 음성용 긴 문자열을 따로 만듭니다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from .models import SortMode, Video


def truncate(text: str, limit: int = 120) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_spoken_time(seconds: float | int | None) -> str:
    """3분 20초 / 1시간 2분 3초 / 20초 / 길이 정보 없음."""
    if seconds is None:
        return "길이 정보 없음"
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "길이 정보 없음"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}시간")
    if minutes:
        parts.append(f"{minutes}분")
    if secs or not parts:
        parts.append(f"{secs}초")
    return " ".join(parts)


def format_clock(seconds: float | int | None) -> str:
    """화면 표시용 1:02:03 형태."""
    try:
        total = max(0, int(float(seconds or 0)))
    except (TypeError, ValueError):
        return "0:00"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_views(count: int | None) -> str:
    """조회수 12만회 / 조회수 1.2억회 / 조회수 934회."""
    if count is None:
        return ""
    try:
        n = int(count)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    if n >= 100_000_000:
        value = n / 100_000_000
        text = f"{value:.1f}".rstrip("0").rstrip(".") + "억"
    elif n >= 10_000:
        value = n / 10_000
        text = (f"{value:.1f}".rstrip("0").rstrip(".") if value < 10 else f"{int(value)}") + "만"
    else:
        return f"조회수 {n:,}회"
    return f"조회수 {text}회"


def _parse_upload_date(raw: str, timestamp: int | None) -> date | None:
    if raw and len(raw) >= 8 and raw[:8].isdigit():
        try:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            return None
    if timestamp:
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def format_date(raw: str = "", timestamp: int | None = None, relative: bool = True) -> str:
    """2026년 10월 20일 (오늘) 형태. 정보가 없으면 빈 문자열."""
    d = _parse_upload_date(raw, timestamp)
    if d is None:
        return ""
    result = f"{d.year}년 {d.month}월 {d.day}일"
    if not relative:
        return result
    days = (date.today() - d).days
    if days == 0:
        return f"{result} 오늘"
    if days == 1:
        return f"{result} 어제"
    if 1 < days < 14:
        return f"{result} {days}일 전"
    if 14 <= days < 60:
        return f"{result} {days // 7}주 전"
    if 60 <= days < 365:
        return f"{result} {days // 30}개월 전"
    return result


def row_display(index: int, video: Video) -> str:
    """표의 한 줄(화면용)."""
    bits = [truncate(video.title, 90)]
    if video.channel:
        bits.append(truncate(video.channel, 28))
    if video.live:
        bits.append("실시간")
    elif video.duration is not None:
        bits.append(format_clock(video.duration))
    date_text = format_date(video.upload_date, video.timestamp, relative=False)
    if date_text:
        bits.append(date_text)
    views = format_views(video.view_count)
    if views:
        bits.append(views)
    return f"{index + 1}. " + " · ".join(b for b in bits if b)


def row_spoken(index: int, video: Video, total: int) -> str:
    """표의 한 줄(음성용). 보이스오버가 이 문자열을 그대로 읽습니다."""
    parts = [f"{index + 1}번, 전체 {total}개 중", truncate(video.title, 160)]
    if video.channel:
        parts.append(f"채널 {truncate(video.channel, 50)}")
    if video.live:
        parts.append("실시간 방송")
    elif video.duration is not None:
        parts.append(f"길이 {format_spoken_time(video.duration)}")
    date_text = format_date(video.upload_date, video.timestamp)
    if date_text:
        parts.append(f"{date_text} 업로드")
    views = format_views(video.view_count)
    if views:
        parts.append(views)
    parts.append("엔터 키 또는 이중 클릭으로 재생합니다.")
    return ", ".join(p for p in parts if p)


def format_position(current: float, duration: float) -> str:
    """l 키를 눌렀을 때 읽어주는 현재 재생 위치."""
    text = f"현재 {format_spoken_time(current)}"
    if duration > 0:
        percent = min(100.0, max(0.0, current / duration * 100))
        text += f", 전체 {format_spoken_time(duration)} 중 {int(percent)}퍼센트"
    else:
        text += ", 전체 길이를 아직 알 수 없습니다"
    return text


def feed_title(mode: SortMode, query: str, home: bool) -> str:
    if mode == SortMode.TRENDING:
        return "인기 급상승 동영상"
    if home:
        return f"최신순 동영상: {query}"
    return f"'{query}' 검색 결과 ({mode.label})"


def status_text(title: str, count: int, exhausted: bool, loading: bool) -> str:
    suffix = "불러오는 중…" if loading else ("마지막 동영상까지 불러왔습니다" if exhausted else f"총 {count}개, 아래로 내려가면 더 불러옵니다")
    return f"{title} · {suffix}"
