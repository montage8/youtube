"""네트워크 없이 앱 전체 흐름을 시험하는 가짜 백엔드.

``python -m ytaccess --demo`` 로 실행하면 실제 유튜브 대신 이 데이터가 표에
나타납니다. 보이스오버 동작, 50개씩 확장, 다운로드 대화상자 등을
인터넷 없이 확인할 때 사용합니다.
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from .models import BackendError, Page, SortMode, Video

_TITLES = [
    "오늘의 주요 뉴스 정리", "맥에서 보이스오버 시작하기", "파이썬으로 만드는 접근성 앱",
    "가을 여행 브이로그", "집에서 만드는 10분 요리", "좋아하는 재즈 플레이리스트",
    "유튜브 광고 없이 보는 방법", "초보자를 위한 코딩 강의", "시각장애인을 위한 기술 소식",
    "한국 전통음악 감상", "날씨와 생활 정보", "오디오북 낭독 모음",
]
_CHANNELS = ["접근성 채널", "오늘의 뉴스", "코딩하는 사람들", "소리로 보는 세상", "생활 정보통"]
_TOTAL = 137  # 50 -> 100 -> 137 (마지막) 까지 확장되는지 확인할 수 있습니다.


class DemoBackend:
    def __init__(self, total: int = _TOTAL) -> None:
        self.total = total
        self.downloaded: list[tuple[str, str]] = []

    def fetch(self, query: str, mode: SortMode, start: int = 1, count: int = 50) -> Page:
        start = max(1, int(start))
        end = min(self.total, start + count - 1)
        if start > self.total:
            return Page([], start, True)
        videos = [self._make_video(i, query, mode) for i in range(start - 1, end)]
        return Page(videos, end + 1, end >= self.total)

    @staticmethod
    def _make_video(index: int, query: str, mode: SortMode) -> Video:
        vid = f"demo{index:06d}"[:11]
        title = _TITLES[index % len(_TITLES)]
        upload = (date.today() - timedelta(days=index // 3)).strftime("%Y%m%d")
        return Video(
            id=vid,
            title=f"[{query} · {mode.label}] {title} {index + 1}편",
            url=f"https://www.youtube.com/watch?v={vid}",
            channel=_CHANNELS[index % len(_CHANNELS)],
            duration=63 + (index * 37) % 3600,
            upload_date=upload,
            view_count=1200 + index * 977,
            description="데모용 동영상입니다.",
        )

    def download_mp4(self, video: Video, directory: str | Path, progress: Callable[[float, str], None] | None = None) -> str:
        destination = Path(directory).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        for percent in (0, 25, 50, 75, 99):
            if progress:
                progress(float(percent), "다운로드 중")
            time.sleep(0.01)
        path = destination / f"{video.title[:60]}.mp4"
        path.write_bytes(b"demo")  # 실제 다운로드가 아님을 분명히 함
        if progress:
            progress(100.0, "완료")
        self.downloaded.append((video.id, str(path)))
        return str(path)

    def resolve_stream(self, video: Video) -> str:
        raise BackendError("데모 모드에서는 직접 스트림을 제공하지 않습니다.")
