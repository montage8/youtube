"""UI와 무관한 앱 두뇌.

- 시작 시 최신순 동영상 50개
- 검색어 입력 -> 새 목록
- 표 커서가 끝에 가까워지면 50개씩 계속 확장 (없을 때까지)
- 재생/링크 복사/MP4 다운로드, 재생 중 키보드 조작

모든 네트워크 작업은 백그라운드 스레드에서 하고, 결과는
``view.run_on_main()`` 을 통해 메인 스레드에서 화면에 반영합니다.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from . import formatting
from .backend import BackendError
from .config import Config
from .models import Page, PlayerState, SortMode, Video
from .speech import Announcer
from .ui.base import SHORTCUT_HELP, View


class InlineExecutor:
    """테스트/데모용: 백그라운드 스레드 없이 즉시 실행."""

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> "Future":
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - 디버깅 편의
            future.set_exception(exc)
        return future

    def shutdown(self, wait: bool = False) -> None:
        pass


class AppController:
    def __init__(
        self,
        config: Config,
        backend: Any,
        view: View,
        announcer: Announcer,
        executor: Any | None = None,
    ) -> None:
        self.config = config
        self.backend = backend
        self.view = view
        self.announcer = announcer
        self.executor = executor if executor is not None else ThreadPoolExecutor(max_workers=3)

        self._lock = threading.RLock()
        self.videos: list[Video] = []
        self._seen: set[str] = set()
        self.query = ""
        self.mode = SortMode.LATEST
        self.home = True
        self.title = ""
        self.cursor = 1
        self.exhausted = False
        self.loading = False
        self.pages_loaded = 0
        self._generation = 0
        self._downloading: set[str] = set()
        self.player_state = PlayerState()

    # ------------------------------------------------------------------ 유틸
    @property
    def announcer_speak(self) -> Callable[[str, str], None]:
        return self.announcer.speak

    def announce(self, text: str, priority: str = "normal") -> None:
        # 화면(View)이 실제 음성 출력을 담당합니다. Cocoa에서는 보이스오버 공지,
        # 터미널에서는 화면 출력, 테스트용 NullView에서는 기록만 합니다.
        self.view.announce(text, priority)

    def _on_main(self, fn: Callable[[], None]) -> None:
        self.view.run_on_main(fn)

    def _submit(self, fn: Callable[..., Any], *args: Any) -> None:
        self.executor.submit(fn, *args)

    def _video_at(self, index: int) -> Video | None:
        with self._lock:
            if 0 <= index < len(self.videos):
                return self.videos[index]
        return None

    def _current_title(self) -> str:
        if self.mode == SortMode.TRENDING:
            return "인기 급상승 동영상"
        if self.home:
            return f"최신순 동영상: {self.query}"
        return f"'{self.query}' 검색 결과 ({self.mode.label})"

    # ------------------------------------------------------------------ 시작/검색
    def start(self) -> None:
        self.home_feed()

    def home_feed(self) -> None:
        """앱을 켰을 때의 화면: 최신순(또는 인기 급상승) 동영상."""
        self._reset(
            query=self.config.home_query.strip() or "뉴스",
            mode=SortMode.TRENDING if self.config.home_mode == "trending" else SortMode.LATEST,
            home=True,
        )
        self._load_first_page()

    def search(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self.announce("검색어를 입력한 뒤 엔터 키를 누르세요.")
            self.view.focus_search()
            return
        mode = SortMode.LATEST if self.config.search_sort == "latest" else SortMode.RELEVANCE
        self._reset(query=query, mode=mode, home=False)
        self.announce(f"{query} 검색 중입니다.")
        self._load_first_page()

    def refresh(self) -> None:
        self._reset(query=self.query, mode=self.mode, home=self.home)
        self.announce("목록을 새로 불러옵니다.")
        self._load_first_page()

    def set_sort(self, name: str) -> None:
        name = name if name in ("relevance", "latest") else "relevance"
        self.config.search_sort = name
        self.config.save()
        mode = SortMode.LATEST if name == "latest" else SortMode.RELEVANCE
        self._reset(query=self.query, mode=mode, home=self.home)
        self.announce(f"{mode.label}으로 정렬합니다.")
        self._load_first_page()

    def set_home_query(self, query: str) -> None:
        query = (query or "").strip()
        if not query:
            self.announce("검색어가 비어 있어 변경하지 않았습니다.", "high")
            return
        self.config.home_query = query
        self.config.save()
        self.announce(f"홈 검색어를 {query}로 변경했습니다.")
        self.home_feed()

    def set_engine(self, engine: str) -> None:
        engine = engine if engine in ("ytplayer", "adfree") else "ytplayer"
        self.config.player_engine = engine
        self.config.save()
        label = "yt-player (유튜브 공식 플레이어)" if engine == "ytplayer" else "광고 없는 직접 재생 (yt-dlp)"
        self.announce(f"재생 엔진을 {label}로 변경했습니다.")

    def _reset(self, query: str, mode: SortMode, home: bool) -> None:
        with self._lock:
            self._generation += 1
            self.query = query
            self.mode = mode
            self.home = home
            self.title = ""
            self.cursor = 1
            self.pages_loaded = 0
            self.exhausted = False
            self.loading = False
            self.videos = []
            self._seen = set()
        self.view.set_rows([], self._current_title(), mode, query, home)

    def _load_first_page(self) -> None:
        with self._lock:
            self._generation += 1
            generation = self._generation
            self.loading = True
        self._update_status("동영상을 불러오는 중입니다…")
        self._submit(self._fetch_worker, generation, 1, self.config.page_size, True)

    def load_more(self) -> None:
        with self._lock:
            if self.loading or self.exhausted:
                return
            if self.pages_loaded >= self.config.max_pages:
                self.exhausted = True
                self.announce("최대 개수까지 불러왔습니다.")
                return
            self.loading = True
            generation = self._generation
            start = self.cursor
            count = self.config.page_size
        self._update_status("동영상을 더 불러오는 중입니다…")
        self._submit(self._fetch_worker, generation, start, count, False)

    def row_selected(self, index: int) -> None:
        """표 커서가 끝에 가까워지면 자동으로 50개를 더 붙입니다."""
        with self._lock:
            count = len(self.videos)
            should_load = (
                not self.loading
                and not self.exhausted
                and count > 0
                and index >= count - self.config.preload_threshold
            )
        if should_load:
            self.load_more()

    def _fetch_worker(self, generation: int, start: int, count: int, replace: bool) -> None:
        try:
            page: Page = self.backend.fetch(self.query, self.mode, start, count)
        except BackendError as exc:
            self._on_main(lambda: self._fetch_failed(generation, str(exc)))
            return
        except Exception as exc:  # 예상치 못한 오류도 화면에 알립니다
            self._on_main(lambda: self._fetch_failed(generation, f"검색 중 오류: {exc}"))
            return
        self._on_main(lambda: self._apply_page(generation, page, replace))

    def _fetch_failed(self, generation: int, message: str) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self.loading = False
            self.exhausted = True
        self._update_status(message)
        self.announce(message, "high")
        self.view.show_error("불러오기 실패", message)

    def _apply_page(self, generation: int, page: Page, replace: bool) -> None:
        with self._lock:
            if generation != self._generation:
                return
            added: list[Video] = []
            for video in page.videos:
                if video.id and video.id in self._seen:
                    continue
                if video.id:
                    self._seen.add(video.id)
                added.append(video)
            self.videos.extend(added)
            self.cursor = max(self.cursor, page.next_start)
            self.pages_loaded += 1
            self.loading = False
            self.exhausted = page.exhausted or not added
            videos = list(self.videos)
            exhausted = self.exhausted
            title = self._current_title()
            mode = self.mode
            query = self.query
            is_home = self.home
            count = len(videos)

        self.title = title
        self.view.set_rows(videos, title, mode, query, is_home)
        self._update_status(formatting.status_text(title, count, exhausted, False))

        if replace:
            if count:
                self.announce(f"{title}. 동영상 {count}개를 불러왔습니다. 위아래 화살표로 이동하고 엔터로 재생합니다.")
                self.view.focus_table()
            else:
                self.announce("검색 결과가 없습니다. 다른 검색어를 입력해 보세요.", "high")
                self.view.focus_search()
        elif added:
            self.announce(f"동영상 {len(added)}개를 더 불러왔습니다. 이제 총 {count}개입니다.")
        elif exhausted:
            self.announce("더 이상 동영상이 없습니다. 마지막 항목입니다.")
        if exhausted and count:
            self._update_status(formatting.status_text(title, count, True, False))

    def _update_status(self, text: str) -> None:
        self.view.set_status(text)

    # ------------------------------------------------------------------ 표 명령
    def play(self, index: int | None = None) -> None:
        video = self._video_at(self.view.selected_index() if index is None else index)
        if video is None:
            self.announce("선택된 동영상이 없습니다.", "high")
            return
        engine = self.config.player_engine
        self.player_state = PlayerState(title=video.title, engine=engine, playback="loading")
        self.announce(f"{video.title} 재생을 준비합니다.")
        if engine == "adfree":
            self._submit(self._resolve_and_play, video)
        else:
            self._on_main(lambda: self.view.open_player(video, "ytplayer", None))

    def _resolve_and_play(self, video: Video) -> None:
        try:
            stream_url = self.backend.resolve_stream(video)
        except BackendError as exc:
            message = str(exc)
            self._on_main(
                lambda: (
                    self.announce(f"{message} yt-player로 전환합니다.", "high"),
                    self.view.open_player(video, "ytplayer", None),
                )
            )
            return
        self._on_main(lambda: self.view.open_player(video, "adfree", stream_url))

    def copy_link(self, index: int | None = None) -> None:
        video = self._video_at(self.view.selected_index() if index is None else index)
        if video is None:
            self.announce("선택된 동영상이 없습니다.", "high")
            return
        self.view.copy_to_clipboard(video.url)
        self.announce(f"{video.title} 링크를 클립보드에 복사했습니다.")

    def download(self, index: int | None = None) -> None:
        video = self._video_at(self.view.selected_index() if index is None else index)
        if video is None:
            self.announce("선택된 동영상이 없습니다.", "high")
            return
        with self._lock:
            if video.id in self._downloading:
                self.announce("이 영상은 이미 다운로드 중입니다.")
                return
        # NSOpenPanel은 반드시 메인 스레드에서 열어야 합니다.
        folder = self.view.choose_download_folder()
        if not folder:
            self.announce("다운로드를 취소했습니다.")
            return
        with self._lock:
            self._downloading.add(video.id)
        self.config.download_dir = str(folder)
        self.config.save()
        self.announce(f"{video.title} 다운로드를 시작합니다. {folder} 에 MP4로 저장합니다.")
        self._submit(self._download_worker, video, str(folder))

    def _download_worker(self, video: Video, folder: str) -> None:
        last_bucket = [-1]

        def progress(percent: float, label: str) -> None:
            bucket = int(percent) // 20
            if bucket != last_bucket[0] and percent < 100:
                last_bucket[0] = bucket
                self._on_main(
                    lambda p=percent, l=label: self._update_status(f"{video.title} · {int(p)}퍼센트 {l}")
                )
            elif percent >= 100 and last_bucket[0] != 5:
                last_bucket[0] = 5
                self._on_main(lambda: self._update_status(f"{video.title} · MP4로 변환하는 중…"))

        try:
            path = self.backend.download_mp4(video, folder, progress)
        except BackendError as exc:
            message = str(exc)
            self._on_main(lambda: self._download_failed(video, message))
            return
        except Exception as exc:
            self._on_main(lambda: self._download_failed(video, f"다운로드 중 오류: {exc}"))
            return
        self._on_main(lambda: self._download_finished(video, path))

    def _download_finished(self, video: Video, path: str) -> None:
        with self._lock:
            self._downloading.discard(video.id)
        filename = Path(path).name if path else ""
        self._update_status(f"다운로드 완료: {filename or video.title}")
        self.announce(f"다운로드 완료. {video.title}. 파일 {filename}. {self.config.download_dir} 폴더에 저장했습니다.", "high")

    def _download_failed(self, video: Video, message: str) -> None:
        with self._lock:
            self._downloading.discard(video.id)
        self._update_status(f"다운로드 실패: {message}")
        self.announce(f"다운로드 실패. {message}", "high")
        self.view.show_error("다운로드 실패", message)

    # ------------------------------------------------------------------ 단축키
    def handle_command(self, action: str) -> bool:
        """메뉴/키 이벤트에서 온 Command 단축키 처리."""
        index = self.view.selected_index()
        handlers: dict[str, Callable[[], None]] = {
            "cmd:f": self.view.focus_search,
            "cmd:l": lambda: self.copy_link(index),
            "cmd:d": lambda: self.download(index),
            "cmd:r": self.refresh,
            "cmd:e": self.load_more,
            "cmd:0": self.home_feed,
            "cmd:1": lambda: self.set_sort("latest"),
            "cmd:2": lambda: self.set_sort("relevance"),
            "cmd:m": self.player_mute,
        }
        fn = handlers.get(action.lower())
        if fn:
            fn()
            return True
        return False

    def handle_player_key(self, action: str) -> bool:
        """재생 창에서 눌린 키 처리. 숫자/화살표/L/Esc 등."""
        if not action:
            return False
        state = self.view.player_state()
        self.player_state = state

        if action == "escape":
            self.view.close_player()
            self.view.focus_table()
            self.announce("재생을 종료하고 동영상 표로 돌아왔습니다.")
            return True
        if action.startswith("digit:"):
            try:
                digit = int(action.split(":", 1)[1])
            except ValueError:
                return False
            percent = digit * 10
            self.view.player_seek_percent(percent)
            if digit == 0:
                self.announce("영상 처음으로 이동했습니다.")
            elif state.duration > 0:
                target = state.duration * percent / 100
                self.announce(f"{percent}퍼센트 지점으로 이동. {formatting.format_spoken_time(target)}.")
            else:
                self.announce(f"{percent}퍼센트 지점으로 이동합니다.")
            return True
        if action in ("left", "right"):
            delta = -self.config.seek_step if action == "left" else self.config.seek_step
            self.view.player_seek_relative(delta)
            target = max(0.0, min(state.duration or 1e9, state.current_time + delta))
            self.announce(f"{self.config.seek_step}초 {'뒤로' if delta < 0 else '앞으로'} 이동. 현재 {formatting.format_spoken_time(target)}.")
            return True
        if action in ("up", "down"):
            delta = self.config.volume_step if action == "up" else -self.config.volume_step
            self.view.player_change_volume(delta)
            volume = min(100.0, max(0.0, state.volume + delta))
            self.announce(f"볼륨 {int(volume)}퍼센트.")
            return True
        if action == "time":
            self.announce(formatting.format_position(state.current_time, state.duration), "high")
            return True
        if action in ("space", "playpause"):
            self.view.player_toggle()
            self.announce("재생 또는 일시정지.")
            return True
        if action == "mute":
            self.view.player_mute()
            self.announce("음소거를 켜거나 끕니다.")
            return True
        return False

    def player_mute(self) -> None:
        self.view.player_mute()
        self.announce("음소거를 켜거나 끕니다.")

    # ------------------------------------------------------------------ 플레이어 상태
    def set_player_state(self, state: PlayerState) -> None:
        self.player_state = state
        title = state.title or "재생 중"
        if state.duration > 0:
            detail = (f"{title} · {formatting.format_clock(state.current_time)} / "
                      f"{formatting.format_clock(state.duration)} · 볼륨 {int(state.volume)}퍼센트")
        else:
            detail = f"{title} · 재생 준비 중 · 볼륨 {int(state.volume)}퍼센트"
        self.view.set_player_status(detail)

    def player_event(self, name: str, detail: str = "") -> None:
        if name == "playing":
            self.announce("재생을 시작했습니다. Esc 키를 누르면 표로 돌아갑니다.")
        elif name == "ended":
            self.announce("동영상 재생이 끝났습니다. Esc 키를 누르면 표로 돌아갑니다.")
        elif name == "autoplay_blocked":
            self.announce("자동 재생이 막혔습니다. 스페이스바를 눌러 재생하세요.", "high")
        elif name == "error":
            self.announce(f"재생 오류: {detail or '알 수 없는 오류'}", "high")
        elif name == "unplayable":
            self.announce("이 영상은 퍼가기가 금지되어 yt-player로 재생할 수 없습니다. Esc로 돌아가 다른 영상을 선택하세요.", "high")

    def player_closed(self) -> None:
        self.view.focus_table()
        self.announce("재생 창이 닫혔습니다. 동영상 표로 돌아왔습니다.")

    @staticmethod
    def help_text() -> str:
        return SHORTCUT_HELP

    def close(self) -> None:
        self.announcer.stop()
        self.executor.shutdown(wait=False)
