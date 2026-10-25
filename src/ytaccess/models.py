"""앱에서 주고받는 단순한 데이터 구조."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class SortMode(str, Enum):
    """동영상 목록의 정렬/공급 방식."""

    LATEST = "latest"        # 업로드 날짜순 검색 (홈 기본값)
    RELEVANCE = "relevance"  # 관련도순 검색
    TRENDING = "trending"    # 유튜브 인기 급상승 피드

    @property
    def label(self) -> str:
        return {
            SortMode.LATEST: "최신순",
            SortMode.RELEVANCE: "관련도순",
            SortMode.TRENDING: "인기 급상승",
        }[self]


@dataclass(frozen=True)
class Video:
    """표에 표시되는 동영상 한 줄."""

    id: str
    title: str
    url: str
    channel: str = ""
    duration: int | None = None       # 초
    upload_date: str = ""             # YYYYMMDD
    timestamp: int | None = None      # Unix epoch (초)
    view_count: int | None = None
    description: str = ""
    live: bool = False

    def __post_init__(self) -> None:
        if not self.title:
            object.__setattr__(self, "title", "제목 없는 동영상")


@dataclass
class Page:
    """검색 결과 한 페이지.

    ``next_start`` 는 제공자(yt-dlp 플레이리스트) 기준 1부터 시작하는 다음
    항목 번호입니다. 표에서 필터링/중복 제거가 일어나도 커서가 어긋나지
    않도록 표의 행 개수가 아니라 이 값을 사용합니다.
    """

    videos: list[Video] = field(default_factory=list)
    next_start: int = 1
    exhausted: bool = False


@dataclass
class PlayerState:
    """WKWebView 안의 플레이어가 0.5초마다 알려주는 상태."""

    engine: str = "none"
    playback: str = "idle"     # idle / loading / playing / paused / buffering / ended / error
    current_time: float = 0.0
    duration: float = 0.0
    volume: float = 100.0
    muted: bool = False
    title: str = ""
    error: str = ""
    message: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PlayerState":
        def number(key: str, default: float = 0.0) -> float:
            try:
                return float(data.get(key, default) or 0)
            except (TypeError, ValueError):
                return default

        return cls(
            engine=str(data.get("engine") or "none"),
            playback=str(data.get("playback") or "idle"),
            current_time=max(0.0, number("currentTime")),
            duration=max(0.0, number("duration")),
            volume=min(100.0, max(0.0, number("volume", 100.0))),
            muted=bool(data.get("muted", False)),
            title=str(data.get("title") or ""),
            error=str(data.get("error") or ""),
            message=str(data.get("message") or ""),
        )


class BackendError(Exception):
    """yt-dlp 호출이 실패했을 때 사용자에게 보여줄 수 있는 오류."""
