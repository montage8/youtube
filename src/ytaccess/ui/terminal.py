"""터미널 화면 (진단 / 백업용).

macOS가 아니거나 PyObjC가 없을 때, 또는 ``--terminal`` 옵션을 줬을 때
사용합니다. 터미널은 VoiceOver와도 궁합이 좋으므로 그래도 쓸 수 있습니다.
단, yt-player의 키보드 재생 조작은 Cocoa 재생 창에서만 동작합니다.
터미널 모드에서는 mpv(설치된 경우) 또는 기본 브라우저로 영상을 엽니다.
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any, Callable

from .. import formatting
from ..config import Config
from ..controller import AppController, InlineExecutor
from ..models import PlayerState, SortMode, Video
from ..speech import Announcer
from .base import SHORTCUT_HELP, View

_HELP = """명령을 입력하세요 (? = 도움말, q = 종료)
  번호              해당 동영상 재생
  s 검색어          유튜브 검색
  m                 동영상 50개 더 불러오기
  show [시작] [개수] 목록 보기 (예: show 45 20)
  n / p             다음 / 이전 20개 보기
  l 번호            링크를 클립보드(터미널에서는 출력)에 복사
  d 번호            MP4 다운로드 (저장 폴더 입력)
  h                 홈(최신순)으로
  r                 새로고침
  homeq 검색어      홈 검색어 변경
  sort latest|relevance   정렬 방식 변경
  engine            재생 엔진 전환
  ?                 전체 키보드 단축키 안내
"""


class TerminalView(View):
    def __init__(self, config: Config) -> None:
        self.config = config
        self.rows: list[Video] = []
        self.status = ""
        self.title = ""
        self.clipboard = ""
        self.player_opened: list[tuple[str, str, str | None]] = []
        self.player_calls: list[tuple[str, Any]] = []
        self.state = PlayerState()
        self.download_folder: str | None = None
        self._page_start = 0
        self._pending: queue.Queue[Callable[[], None]] = queue.Queue()
        self._lock = threading.RLock()
        self._quit = False
        self.controller: AppController | None = None

    # ------------------------------------------------------------------ View API
    def set_rows(self, videos: list[Video], title: str, mode: SortMode, query: str, home: bool) -> None:
        with self._lock:
            self.rows = list(videos)
            self.title = title
            self._page_start = 0
        if videos:
            self.show_rows(0, 20)

    def set_status(self, text: str, announce: bool = False) -> None:
        self.status = text
        print(f"[상태] {text}", flush=True)

    def announce(self, text: str, priority: str = "normal") -> None:
        print(f"[안내] {text}", flush=True)

    def set_player_status(self, text: str) -> None:
        self.status = text

    def focus_table(self) -> None:
        pass

    def focus_search(self) -> None:
        print("[안내] 's 검색어' 형태로 입력하면 검색합니다.", flush=True)

    def selected_index(self) -> int:
        return 0

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard = text
        print(f"[클립보드] {text}", flush=True)

    def choose_download_folder(self) -> str | None:
        if self.download_folder:
            return self.download_folder
        print(f"저장 폴더 경로를 입력하세요 (엔터 = {self.config.download_path}): ", end="", flush=True)
        line = sys.stdin.readline()
        answer = line.strip() if line else ""
        return str(self.config.download_path) if not answer else answer

    def run_on_main(self, fn: Callable[[], None]) -> None:
        self._pending.put(fn)

    def open_player(self, video: Video, engine: str, stream_url: str | None = None) -> None:
        self.player_opened.append((video.id, engine, stream_url))
        url = stream_url or video.url
        mpv = shutil.which("mpv")
        print(f"[재생] {video.title} (엔진: {engine})", flush=True)
        if mpv:
            try:
                subprocess.Popen([mpv, "--force-window=yes", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("[안내] mpv 재생 창을 열었습니다. mpv의 키보드 조작을 사용하세요.", flush=True)
                return
            except OSError:
                pass
        try:
            webbrowser.open(video.url)
            print("[안내] 기본 브라우저에서 영상을 열었습니다. yt-player 재생 조작은 macOS 앱 창에서만 동작합니다.", flush=True)
        except Exception:
            print(f"[안내] 직접 여세요: {video.url}", flush=True)

    def close_player(self) -> None:
        pass

    def player_state(self) -> PlayerState:
        return self.state

    def player_seek(self, seconds: float) -> None:
        self.player_calls.append(("seek", seconds))

    def player_seek_percent(self, percent: float) -> None:
        self.player_calls.append(("seek_percent", percent))

    def player_seek_relative(self, delta: float) -> None:
        self.player_calls.append(("seek_relative", delta))

    def player_set_volume(self, value: float) -> None:
        self.player_calls.append(("volume", value))

    def player_change_volume(self, delta: float) -> None:
        self.player_calls.append(("change_volume", delta))

    def player_toggle(self) -> None:
        self.player_calls.append(("toggle", None))

    def player_mute(self) -> None:
        self.player_calls.append(("mute", None))

    # ------------------------------------------------------------------ 실행 루프
    def _drain(self) -> None:
        while True:
            try:
                fn = self._pending.get_nowait()
            except queue.Empty:
                return
            fn()

    def show_rows(self, start: int | None = None, count: int = 20) -> None:
        with self._lock:
            first = self._page_start if start is None else max(0, start)
            total = len(self.rows)
            if first >= total and total:
                first = max(0, total - count)
            self._page_start = first
            end = min(total, first + count)
            print(f"\n=== {self.title or '동영상'} (전체 {total}개) ===", flush=True)
            for i in range(first, end):
                print(f"  {formatting.row_display(i, self.rows[i])}", flush=True)
            if not total:
                print("  (동영상이 없습니다)", flush=True)
            print(f"=== {first + 1}~{end} / {total} · 'n' 다음, 'm' 더 불러오기, 번호=재생 ===\n", flush=True)

    def run(self, controller: AppController) -> int:
        self.controller = controller
        print("=" * 72, flush=True)
        print(" 유튜브 접근성 (ytaccess) — 터미널 모드", flush=True)
        print("=" * 72, flush=True)
        print(_HELP, flush=True)
        controller.start()

        while not self._quit:
            self._drain()
            if sys.stdin.isatty():
                print("명령> ", end="", flush=True)
            line = sys.stdin.readline()
            if not line:
                self._drain()
                break
            text = line.strip()
            if not text:
                self._drain()
                continue
            self.handle(text)
            self._drain()
        return 0

    def handle(self, text: str) -> None:
        if not self.controller:
            return
        c = self.controller
        lower = text.lower()
        parts = text.split(maxsplit=1)
        head = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""

        if lower in ("q", "quit", "exit", "종료"):
            self._quit = True
            return
        if text in ("?", "help", "도움말"):
            print(_HELP)
            return
        if lower in ("keys", "단축키"):
            print(SHORTCUT_HELP)
            return
        if lower in ("h", "home", "홈"):
            c.home_feed()
        elif lower in ("m", "more", "더보기"):
            c.load_more()
        elif lower in ("r", "refresh", "새로고침"):
            c.refresh()
        elif lower == "engine":
            c.set_engine("adfree" if self.config.player_engine == "ytplayer" else "ytplayer")
        elif lower in ("n", "next"):
            self.show_rows(self._page_start + 20)
        elif lower in ("p", "prev"):
            self.show_rows(max(0, self._page_start - 20))
        elif lower in ("show", "list", "목록"):
            args = rest.split()
            start = int(args[0]) - 1 if args and args[0].isdigit() else None
            count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 20
            self.show_rows(start, count)
        elif lower in ("s", "search", "검색"):
            if not rest:
                print("사용법: s 검색어")
            else:
                c.search(rest)
        elif lower in ("homeq", "home_search"):
            c.set_home_query(rest) if rest else print("사용법: homeq 검색어")
        elif lower in ("sort", "정렬"):
            c.set_sort("latest" if rest in ("latest", "최신순") else "relevance")
        elif lower in ("l", "link"):
            if rest.isdigit():
                c.copy_link(int(rest) - 1)
            else:
                print("사용법: l 번호")
        elif lower in ("d", "download", "다운로드"):
            if rest.isdigit():
                c.download(int(rest) - 1)
            else:
                print("사용법: d 번호")
        elif head.isdigit():
            c.play(int(head) - 1)
        else:
            print(f"알 수 없는 명령: {text} (? 입력 시 도움말)")


def run_terminal(config: Config, backend: Any, announcer: Announcer, demo: bool = False) -> int:
    view = TerminalView(config)
    # 터미널은 입력 대기 중에도 결과가 즉시 보여야 하므로 동기 실행기를 씁니다.
    controller = AppController(config, backend, view, announcer, executor=InlineExecutor())
    try:
        return view.run(controller)
    except KeyboardInterrupt:
        print("\n종료합니다.", flush=True)
        return 0
    finally:
        controller.close()
