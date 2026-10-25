"""화면(View) 인터페이스와 키보드 입력을 앱 동작 이름으로 바꾸는 함수.

컨트롤러는 이 인터페이스만 알기 때문에 Cocoa 화면, 터미널 화면,
테스트용 가짜 화면을 모두 같은 로직으로 검증할 수 있습니다.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..models import PlayerState, SortMode, Video

# macOS 가상 키 코드
KEY_ESCAPE = 53
KEY_RETURN = 36
KEY_KEYPAD_ENTER = 76
KEY_SPACE = 49
# 재생 창 전용 키 (물리 키 위치 기준이라 한글 입력 상태에서도 동작)
KEY_D = 2            # 볼륨 내리기
KEY_S = 1            # 재생 속도 느리게
KEY_F = 3            # 재생 속도 빠르게
KEY_U = 32           # 볼륨 올리기
KEY_APOSTROPHE = 39  # 5초 앞으로
KEY_SEMICOLON = 41   # 5초 뒤로
PLAYER_LETTER_ACTIONS = {
    KEY_D: "volume_down",
    KEY_U: "volume_up",
    KEY_S: "speed_down",
    KEY_F: "speed_up",
    KEY_APOSTROPHE: "seek_forward",
    KEY_SEMICOLON: "seek_back",
}
KEY_KEYPAD_DIGITS = {
    82: "0", 83: "1", 84: "2", 85: "3", 86: "4",
    87: "5", 88: "6", 89: "7", 91: "8", 92: "9",
}


def normalize_key_action(chars: str = "", keycode: int | None = None, command: bool = False) -> str | None:
    """NSEvent 정보를 'digit:3', 'left', 'time', 'cmd:f' 같은 동작 이름으로 변환."""
    chars = chars or ""
    if keycode == KEY_ESCAPE or chars.startswith("\x1b"):
        return "escape"
    if keycode in KEY_KEYPAD_DIGITS:
        return "digit:" + KEY_KEYPAD_DIGITS[keycode]
    if command and chars:
        return "cmd:" + chars.lower()
    if keycode in PLAYER_LETTER_ACTIONS:
        return PLAYER_LETTER_ACTIONS[keycode]
    if keycode in (KEY_RETURN, KEY_KEYPAD_ENTER) or chars[:1] in ("\r", "\n", "\x03"):
        return "return"
    if keycode == KEY_SPACE or chars[:1] == " ":
        return "space"
    if chars[:1].isdigit():
        return "digit:" + chars[0]
    lowered = chars.lower()
    if lowered.startswith("l"):
        return "time"
    if lowered.startswith("m"):
        return "mute"
    if lowered.startswith("p"):
        return "playpause"
    return None


SHORTCUT_HELP = """유튜브 접근성 프로그램 키보드 단축키

[동영상 표]
위/아래 화살표  이전/다음 동영상으로 이동 (보이스오버가 제목, 채널, 길이, 날짜, 조회수를 읽어줍니다)
엔터 또는 이중 클릭  선택한 동영상 재생
Command+F  검색창으로 이동 (검색어 입력 후 엔터)
Command+L  선택한 동영상의 링크를 클립보드에 복사
Command+D  선택한 동영상을 MP4로 다운로드 (저장 폴더 선택 대화상자)
Command+R  현재 목록 새로고침
Command+E  동영상 50개 더 불러오기 (표 끝에 가면 자동으로 불러옵니다)
Command+1  최신순으로 정렬 / Command+2  관련도순으로 정렬
Command+0  홈(최신순 동영상)으로 돌아가기
Command+,  홈 검색어 변경

[재생 중]
숫자 0~9 (키패드 포함)  영상 길이의 0~90퍼센트 지점으로 이동 (0은 처음)
; (세미콜론)  5초 뒤로
' (아포스트로피)  5초 앞으로
U  볼륨 올리기
D  볼륨 내리기
F  재생 속도 빠르게 (0.25배부터 2배까지 단계별로)
S  재생 속도 느리게 (0.25배부터 2배까지 단계별로)
L  현재 재생 위치를 음성으로 읽어주기
Command+T  연속 반복 켜기 / 끄기 (켜면 영상이 끝나도 같은 영상을 다시 재생)
Command+N  다음 영상 자동 재생 켜기 / 끄기 (재생목록에서 재생한 경우, 끝나면 바로 아래 영상 재생)
스페이스바  재생 / 일시정지
M  음소거 켜기 / 끄기
Esc  재생 종료 후 동영상 표로 돌아가기

[음성 안내]
보이스오버가 켜져 있으면 보이스오버가, 꺼져 있으면 macOS의 'say' 음성이 안내합니다.
설정 파일의 speech_mode 로 방식을 바꿀 수 있습니다.
"""


class View:
    """컨트롤러가 호출하는 화면 API. 기본 구현은 아무 것도 하지 않습니다."""

    # ---- 표 ----
    def set_rows(self, videos: list[Video], title: str, mode: SortMode, query: str, home: bool) -> None:
        pass

    def set_status(self, text: str, announce: bool = False) -> None:
        pass

    def focus_table(self) -> None:
        pass

    def focus_search(self) -> None:
        pass

    def selected_index(self) -> int:
        return 0

    # ---- 안내 ----
    def announce(self, text: str, priority: str = "normal") -> None:
        pass

    def show_error(self, title: str, message: str) -> None:
        self.announce(f"{title}. {message}", "high")

    # ---- 시스템 ----
    def copy_to_clipboard(self, text: str) -> None:
        pass

    def choose_download_folder(self) -> str | None:
        return None

    def run_on_main(self, fn: Callable[[], None]) -> None:
        fn()

    def set_config_value(self, key: str, value: Any) -> None:
        pass

    # ---- 플레이어 ----
    def open_player(self, video: Video, engine: str, stream_url: str | None = None) -> None:
        pass

    def close_player(self) -> None:
        pass

    def set_player_status(self, text: str) -> None:
        pass

    def player_state(self) -> PlayerState:
        return PlayerState()

    def player_seek(self, seconds: float) -> None:
        pass

    def player_seek_percent(self, percent: float) -> None:
        pass

    def player_seek_relative(self, delta: float) -> None:
        pass

    def player_set_volume(self, value: float) -> None:
        pass

    def player_change_volume(self, delta: float) -> None:
        pass

    def player_toggle(self) -> None:
        pass

    def player_mute(self) -> None:
        pass

    def player_restart(self) -> None:
        pass

    def player_set_rate(self, rate: float) -> None:
        pass


class NullView(View):
    """테스트/헤드리스 실행용 화면. 모든 호출을 기록합니다."""

    def __init__(self) -> None:
        self.rows: list[Video] = []
        self.status = ""
        self.title = ""
        self.announcements: list[str] = []
        self.errors: list[tuple[str, str]] = []
        self.clipboard = ""
        self.player_calls: list[tuple[str, Any]] = []
        self.player_opened: list[tuple[str, str, str | None]] = []
        self.player_closed = 0
        self.table_focused = 0
        self.search_focused = 0
        self.selection = 0
        self.download_folder: str | None = None
        self.state = PlayerState()
        self.player_status = ""
        self.config_changes: list[tuple[str, Any]] = []
        self.lock = threading.RLock()

    def set_rows(self, videos, title, mode, query, home) -> None:
        with self.lock:
            self.rows = list(videos)
            self.title = title

    def set_status(self, text: str, announce: bool = False) -> None:
        with self.lock:
            self.status = text
            if announce:
                self.announcements.append(text)

    def focus_table(self) -> None:
        self.table_focused += 1

    def focus_search(self) -> None:
        self.search_focused += 1

    def selected_index(self) -> int:
        return self.selection

    def announce(self, text: str, priority: str = "normal") -> None:
        with self.lock:
            self.announcements.append(text)

    def show_error(self, title: str, message: str) -> None:
        with self.lock:
            self.errors.append((title, message))
            self.announcements.append(f"{title}. {message}")

    def copy_to_clipboard(self, text: str) -> None:
        self.clipboard = text

    def choose_download_folder(self) -> str | None:
        return self.download_folder

    def set_config_value(self, key: str, value) -> None:
        self.config_changes.append((key, value))

    def open_player(self, video: Video, engine: str, stream_url: str | None = None) -> None:
        self.player_opened.append((video.id, engine, stream_url))

    def close_player(self) -> None:
        self.player_closed += 1

    def set_player_status(self, text: str) -> None:
        self.player_status = text

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

    def player_restart(self) -> None:
        self.player_calls.append(("restart", None))

    def player_set_rate(self, rate: float) -> None:
        self.player_calls.append(("set_rate", rate))
