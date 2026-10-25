"""yt-dlp 기반 검색 / MP4 다운로드 / 재생용 스트림 URL 추출.

검색은 API 키가 필요 없는 yt-dlp의 YouTube 검색 추출기를 사용합니다.
- 최신순: https://www.youtube.com/results?search_query=...&sp=CAISAhAB
- 관련도순: ...&sp=EgIQAfABAQ%3D%3D
- 인기 급상승: https://www.youtube.com/feed/trending

yt-dlp 버전에 따라 위 URL 추출기가 없는 경우를 대비해
``ytsearchN:`` / ``ytsearchdateN:`` 문법으로 자동 폴백합니다.
다른 검색 서비스로 바꾸고 싶다면 ``fetch`` 메서드만 같은 모양으로 구현하면 됩니다.
"""

from __future__ import annotations

import re
import threading
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .models import BackendError, Page, SortMode, Video

# YouTube 검색 필터(sp) 값. yt-dlp의 YoutubeSearchURLIE가 그대로 사용합니다.
_SEARCH_FILTERS = {
    SortMode.LATEST: "CAISAhAB",           # 동영상만, 업로드 날짜순
    SortMode.RELEVANCE: "EgIQAfABAQ%3D%3D",  # 동영상만, 관련도순
}

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

ProgressCallback = Callable[[float, str], None]


class SearchProvider(Protocol):
    """다른 검색 백엔드를 끼울 때 따를 인터페이스."""

    def fetch(self, query: str, mode: SortMode, start: int, count: int) -> Page: ...
    def download_mp4(self, video: Video, directory: str | Path, progress: ProgressCallback | None = None) -> str: ...
    def resolve_stream(self, video: Video) -> str: ...


class YtDlpBackend:
    def __init__(
        self,
        language: str = "ko",
        region: str = "KR",
        cookies_from_browser: str = "",
        download_subtitles: bool = False,
        ytdlp_module: Any | None = None,
    ) -> None:
        self.language = language
        self.region = region
        self.cookies_from_browser = cookies_from_browser.strip()
        self.download_subtitles = download_subtitles
        self._lock = threading.Lock()  # YoutubeDL 인스턴스는 스레드 간 공유하지 않습니다
        if ytdlp_module is None:
            try:
                import yt_dlp  # noqa: F401  (지연 임포트)
            except ImportError as exc:  # pragma: no cover - 실제 맥에서만 발생
                raise BackendError(
                    "yt-dlp가 설치되지 않았습니다. 'pip install -U yt-dlp' 또는 "
                    "'scripts/setup_mac.sh'를 실행해 주세요."
                ) from exc
            ytdlp_module = yt_dlp
        self._ytdlp = ytdlp_module

    # ------------------------------------------------------------------ 공통 옵션
    def _options(self, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": False,
            "ignoreerrors": True,
            "retries": 2,
            "socket_timeout": 20,
            "geo_bypass_country": self.region,
        }
        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)
        if extra:
            opts.update(extra)
        return opts

    def _search_urls(self, query: str, mode: SortMode, limit: int) -> list[str]:
        """우선순위대로 시도할 yt-dlp 입력 URL 목록."""
        if mode == SortMode.TRENDING:
            urls = [f"https://www.youtube.com/feed/trending?hl={self.language}&gl={self.region}"]
        else:
            encoded = urllib.parse.quote_plus(query or "")
            sp = _SEARCH_FILTERS.get(mode, _SEARCH_FILTERS[SortMode.RELEVANCE])
            urls = [
                "https://www.youtube.com/results?"
                f"search_query={encoded}&sp={sp}&hl={self.language}&gl={self.region}",
                f"ytsearchdate{limit}:{query}" if mode == SortMode.LATEST else f"ytsearch{limit}:{query}",
                f"ytsearch{limit}:{query}",
            ]
        if mode == SortMode.TRENDING:
            urls.append(f"ytsearch{limit}:{query or '인기 동영상'}")
        return urls

    # ------------------------------------------------------------------ 검색
    def fetch(self, query: str, mode: SortMode, start: int = 1, count: int = 50) -> Page:
        start = max(1, int(start))
        count = max(1, int(count))
        limit = start + count - 1
        candidates = self._search_urls(query, mode, limit)
        last_error: Exception | None = None

        for url in candidates:
            opts = self._options(
                {
                    "skip_download": True,
                    "extract_flat": "in_playlist",
                    "playliststart": start,
                    "playlistend": limit,
                }
            )
            try:
                with self._ytdlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                raw_entries = self._extract_entries(info)
                videos = self._to_videos(raw_entries)
                if videos:
                    return Page(
                        videos=videos,
                        next_start=start + len(raw_entries),
                        exhausted=len(raw_entries) < count,
                    )
                last_error = None  # 결과가 비었으면 정상적으로 '마지막'으로 처리
            except Exception as exc:  # yt-dlp는 다양한 예외를 던집니다
                last_error = exc
                continue

        if last_error is not None:
            raise BackendError(f"검색에 실패했습니다: {last_error}")
        return Page(videos=[], next_start=start, exhausted=True)

    @staticmethod
    def _extract_entries(info: Any) -> list[Mapping[str, Any]]:
        if not info or not isinstance(info, dict):
            return []
        entries = info.get("entries") or []
        if not isinstance(entries, (list, tuple)):
            try:
                entries = list(entries)
            except TypeError:
                return []
        return [e for e in entries if isinstance(e, Mapping)]

    @staticmethod
    def _to_videos(entries: Iterable[Mapping[str, Any]]) -> list[Video]:
        videos: list[Video] = []
        for entry in entries:
            video = YtDlpBackend._to_video(entry)
            if video is not None:
                videos.append(video)
        return videos

    @staticmethod
    def _to_video(entry: Mapping[str, Any]) -> Video | None:
        video_id = str(entry.get("id") or "")
        url = str(entry.get("url") or entry.get("webpage_url") or "")
        if url and not url.startswith(("http://", "https://")):
            url = f"https://www.youtube.com/watch?v={url}"
        if not url.startswith(("http://", "https://")) and _VIDEO_ID.match(video_id):
            url = f"https://www.youtube.com/watch?v={video_id}"
        # 검색 결과에 섞여 들어온 채널/재생목록 항목은 제외합니다.
        if "youtube.com/watch" not in url and "youtu.be/" not in url:
            return None
        if not video_id:
            match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
            video_id = match.group(1) if match else url.rsplit("/", 1)[-1]

        timestamp = _as_int(entry.get("timestamp"))
        upload_date = str(entry.get("upload_date") or "")
        if not upload_date and timestamp:
            try:
                upload_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y%m%d")
            except (OverflowError, OSError, ValueError):
                upload_date = ""

        return Video(
            id=video_id,
            title=str(entry.get("title") or "제목 없는 동영상"),
            url=url,
            channel=str(entry.get("channel") or entry.get("uploader") or entry.get("uploader_id") or ""),
            duration=_as_int(entry.get("duration")),
            upload_date=upload_date,
            timestamp=timestamp,
            view_count=_as_int(entry.get("view_count")),
            description=str(entry.get("description") or "")[:500],
            live=str(entry.get("live_status") or "") in ("is_live", "live") or bool(entry.get("is_live")),
        )

    # ------------------------------------------------------------------ 다운로드
    def download_mp4(
        self,
        video: Video,
        directory: str | Path,
        progress: ProgressCallback | None = None,
    ) -> str:
        destination = Path(directory).expanduser()
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BackendError(f"저장 폴더를 만들 수 없습니다: {exc}") from exc

        finished_paths: list[str] = []

        def hook(data: Mapping[str, Any]) -> None:
            if not progress:
                return
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                done = data.get("downloaded_bytes") or 0
                percent = min(99.0, done / total * 100) if total else 0.0
                progress(percent, "다운로드 중")
            elif status == "finished":
                path = data.get("filename") or data.get("info_dict", {}).get("filepath")
                if path:
                    finished_paths.append(str(path))
                progress(100.0, "변환 중")

        def pp_hook(data: Mapping[str, Any]) -> None:
            if data.get("status") == "finished" and progress:
                progress(100.0, "완료")
            path = data.get("info_dict", {}).get("filepath") if isinstance(data.get("info_dict"), Mapping) else None
            if path:
                finished_paths.append(str(path))

        template = str(destination / "%(title).120B [%(id)s].%(ext)s")
        opts = self._options(
            {
                "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
                "merge_output_format": "mp4",
                "outtmpl": {"default": template},
                "overwrites": False,
                "continuedl": True,
                "progress_hooks": [hook],
                "postprocessor_hooks": [pp_hook],
                "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
                "writesubtitles": self.download_subtitles,
                "writeautomaticsub": self.download_subtitles,
                "subtitleslangs": ["ko", "ko-KR", "en", "en-US"],
                "ignoreerrors": False,
                "retries": 3,
            }
        )

        try:
            with self._ytdlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.url, download=True)
        except Exception as exc:
            raise BackendError(f"다운로드에 실패했습니다: {exc}") from exc

        filepath = _find_download_path(info, finished_paths)
        if progress:
            progress(100.0, "완료")
        return filepath or str(destination)

    # ------------------------------------------------------------------ 광고 없는 재생
    def resolve_stream(self, video: Video) -> str:
        """WKWebView의 <video>에서 바로 재생할 수 있는 progressive 스트림 URL."""
        opts = self._options(
            {
                "skip_download": True,
                "quiet": True,
                "format": "best[ext=mp4][acodec!=none][vcodec!=none]"
                          "/best[acodec!=none][vcodec!=none]/best",
            }
        )
        try:
            with self._ytdlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video.url, download=False)
        except Exception as exc:
            raise BackendError(f"재생 주소를 얻지 못했습니다: {exc}") from exc
        if not info:
            raise BackendError("재생 주소를 얻지 못했습니다.")
        url = info.get("url")
        if not url and info.get("requested_formats"):
            url = info["requested_formats"][0].get("url")
        if not url:
            raise BackendError("이 영상은 직접 재생 주소를 제공하지 않습니다. yt-player 엔진을 사용해 주세요.")
        return str(url)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _find_download_path(info: Any, fallbacks: list[str]) -> str | None:
    candidates: list[str] = []
    if isinstance(info, Mapping):
        for item in info.get("requested_downloads") or []:
            if isinstance(item, Mapping) and item.get("filepath"):
                candidates.append(str(item["filepath"]))
        if info.get("filepath"):
            candidates.append(str(info["filepath"]))
    candidates.extend(reversed([p for p in fallbacks if p]))
    for path in candidates:
        if path.lower().endswith(".mp4"):
            return path
    if candidates:
        return str(Path(candidates[0]).with_suffix(".mp4"))
    return None
