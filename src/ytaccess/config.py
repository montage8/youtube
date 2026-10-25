"""사용자 설정. macOS에서는 ~/Library/Application Support/ytaccess/settings.json."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Mapping


def default_config_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "ytaccess"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ytaccess"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ytaccess"
    return base / "settings.json"


def default_download_dir() -> Path:
    """macOS 한국어 시스템에서도 실제로 존재하는 다운로드 폴더."""
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        return downloads
    return Path.home() / "다운로드"


@dataclass
class Config:
    # 목록 / 무한 확장
    page_size: int = 50                  # 한 번에 늘려 보여줄 동영상 수 (50 -> 100 -> 150 ...)
    preload_threshold: int = 5           # 마지막에서 몇 개 남았을 때 확장할지
    max_pages: int = 30                  # 안전장치 (50 * 30 = 1500개)
    home_mode: str = "latest"            # latest | trending
    home_query: str = "뉴스"             # 홈에서 최신순으로 보여줄 기본 검색어
    search_sort: str = "relevance"       # relevance | latest (검색 결과 정렬)

    # 재생
    player_engine: str = "ytplayer"      # ytplayer(유튜브 iframe) | adfree(yt-dlp 직접 스트림)
    seek_step: int = 5                   # 좌우 화살표 이동 초
    volume_step: int = 10                # 위아래 화살표 볼륨 단계
    start_volume: int = 100

    # 음성 안내
    speech_mode: str = "auto"            # auto | voiceover | say | both | off
    speech_voice: str = ""               # 비우면 한국어 목소리 자동 선택
    speech_rate: int = 200               # say 명령의 분당 단어 수

    # 다운로드
    download_dir: str = ""               # 비우면 ~/Downloads
    download_subtitles: bool = False     # 자막도 함께 저장 (ffmpeg 필요)

    # yt-dlp
    language: str = "ko"
    region: str = "KR"
    cookies_from_browser: str = ""       # 예: safari, chrome (연령 제한 영상용)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Config":
        known = {f.name for f in fields(cls)}
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known:
                continue
            expected = getattr(cls(), key)
            try:
                if isinstance(expected, bool):
                    clean[key] = bool(value)
                elif isinstance(expected, int):
                    clean[key] = int(value)
                elif isinstance(expected, str):
                    clean[key] = str(value)
            except (TypeError, ValueError):
                continue
        cfg = cls(**clean)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        self.page_size = min(100, max(10, self.page_size))
        self.preload_threshold = min(self.page_size - 1, max(1, self.preload_threshold))
        self.max_pages = max(1, self.max_pages)
        self.seek_step = min(60, max(1, self.seek_step))
        self.volume_step = min(50, max(1, self.volume_step))
        self.start_volume = min(100, max(0, self.start_volume))
        self.speech_rate = min(400, max(80, self.speech_rate))
        if self.home_mode not in ("latest", "trending"):
            self.home_mode = "latest"
        if self.search_sort not in ("relevance", "latest"):
            self.search_sort = "relevance"
        if self.player_engine not in ("ytplayer", "adfree"):
            self.player_engine = "ytplayer"
        if self.speech_mode not in ("auto", "voiceover", "say", "both", "off"):
            self.speech_mode = "auto"
        if not self.home_query.strip():
            self.home_query = "뉴스"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "Config":
        target = Path(path) if path else default_config_path()
        if not target.exists():
            return cls()
        try:
            with target.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                cfg = cls()
            else:
                cfg = cls.from_mapping(data)
        except (OSError, ValueError, TypeError):
            cfg = cls()
        cfg._save_path = target  # type: ignore[attr-defined]
        return cfg

    def save(self, path: str | os.PathLike[str] | None = None) -> Path:
        target = Path(path) if path else Path(getattr(self, "_save_path", None) or default_config_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
        tmp.replace(target)
        return target

    @property
    def download_path(self) -> Path:
        path = Path(self.download_dir).expanduser() if self.download_dir else default_download_dir()
        return path
