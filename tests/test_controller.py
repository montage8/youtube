"""컨트롤러 로직 단위 테스트.

맥이 아닌 환경(Cocoa/PyObjC 없는 리눅스 등)에서도 실행 가능하도록,
DemoBackend + NullView 만 사용합니다.
"""

from __future__ import annotations

from ytaccess import formatting
from ytaccess.controller import AppController, InlineExecutor
from ytaccess.demo_backend import DemoBackend
from ytaccess.models import SortMode, Video
from ytaccess.speech import Announcer
from ytaccess.ui.base import NullView


def _make_app(total: int = 137) -> tuple[AppController, NullView]:
    from ytaccess.config import Config

    config = Config()
    config.speech_mode = "off"
    config.page_size = 50
    backend = DemoBackend(total=total)
    view = NullView()
    announcer = Announcer(config, voiceover_detector=lambda: False)
    controller = AppController(config, backend, view, announcer, executor=InlineExecutor())
    return controller, view


def test_start_shows_50_latest_videos() -> None:
    controller, view = _make_app()
    controller.start()
    assert len(view.rows) == 50
    assert "최신순" in view.title
    assert view.announcements
    assert "50개" in view.announcements[-1]


def test_load_more_doubles_to_100() -> None:
    controller, view = _make_app()
    controller.start()
    controller.load_more()
    assert len(view.rows) == 100


def test_auto_expand_near_end_until_exhausted() -> None:
    controller, view = _make_app(total=137)
    controller.start()
    assert len(view.rows) == 50
    view.selection = 45  # 50개 중 마지막 5개 → 자동 확장
    controller.row_selected(45)
    assert len(view.rows) == 100
    view.selection = 96  # 100개 중 마지막 5개 → 자동 확장
    controller.row_selected(96)
    assert len(view.rows) == 137
    assert controller.exhausted


def test_search_resets_list() -> None:
    controller, view = _make_app()
    controller.start()
    controller.search("보이스오버")
    assert len(view.rows) == 50
    assert "보이스오버" in view.rows[0].title
    assert view.table_focused >= 1


def test_copy_link() -> None:
    controller, view = _make_app()
    controller.start()
    view.selection = 3
    controller.copy_link(3)
    assert view.clipboard == view.rows[3].url
    assert view.clipboard.startswith("https://www.youtube.com/watch?v=")


def test_download_records_and_announces() -> None:
    controller, view = _make_app()
    controller.start()
    view.download_folder = "/tmp/ytaccess-test-downloads"
    controller.download(1)
    assert len(controller.backend.downloaded) == 1
    assert any("다운로드 완료" in a for a in view.announcements)


def test_play_and_escape_returns_to_table() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(2)
    assert len(view.player_opened) == 1
    assert view.player_opened[0][0] == view.rows[2].id
    controller.handle_player_key("escape")
    assert view.player_closed == 1
    assert view.table_focused >= 1


def test_player_seek_percent_and_relative() -> None:
    controller, view = _make_app()
    controller.start()
    view.state = view.state.__class__(current_time=100.0, duration=1000.0, volume=50.0)
    controller.handle_player_key("digit:3")
    assert ("seek_percent", 30.0) in view.player_calls
    controller.handle_player_key("seek_back")
    assert ("seek_relative", -5.0) in view.player_calls
    controller.handle_player_key("seek_forward")
    assert ("seek_relative", 5.0) in view.player_calls


def test_player_volume_and_time() -> None:
    controller, view = _make_app()
    controller.start()
    view.state = view.state.__class__(current_time=125.0, duration=500.0, volume=60.0)
    controller.handle_player_key("volume_up")
    assert ("change_volume", 10.0) in view.player_calls
    controller.handle_player_key("volume_down")
    assert ("change_volume", -10.0) in view.player_calls
    controller.handle_player_key("time")
    assert any("2분 5초" in a for a in view.announcements)


def test_digit_zero_seeks_to_start() -> None:
    controller, view = _make_app()
    controller.start()
    view.state = view.state.__class__(current_time=100.0, duration=1000.0, volume=50.0)
    controller.handle_player_key("digit:0")
    assert ("seek_percent", 0.0) in view.player_calls


def test_max_pages_cap() -> None:
    controller, view = _make_app(total=10000)
    controller.config.max_pages = 1
    controller.start()
    controller.load_more()
    assert controller.exhausted


def test_home_query_change() -> None:
    controller, view = _make_app()
    controller.start()
    controller.set_home_query("새 소식")
    assert controller.config.home_query == "새 소식"
    assert controller.query == "새 소식"


def test_engine_toggle() -> None:
    controller, view = _make_app()
    controller.start()
    controller.set_engine("adfree")
    assert controller.config.player_engine == "adfree"
    controller.set_engine("ytplayer")
    assert controller.config.player_engine == "ytplayer"


def test_row_spoken_contains_position_and_title() -> None:
    controller, view = _make_app()
    controller.start()
    spoken = formatting.row_spoken(0, view.rows[0], len(view.rows))
    assert "1번" in spoken
    assert view.rows[0].title in spoken
    assert "재생합니다" in spoken


def test_repeat_toggle_restarts_same_video_on_end() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(0)
    controller.handle_command("cmd:t")
    assert controller.repeat_one
    controller.player_event("ended")
    assert ("restart", None) in view.player_calls
    assert len(view.player_opened) == 1  # 새 영상을 열지 않고 같은 영상을 다시 재생

    controller.handle_command("cmd:t")
    assert not controller.repeat_one


def test_auto_next_plays_row_below_when_ended() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(3)
    controller.handle_command("cmd:n")
    assert controller.auto_next
    controller.player_event("ended")
    assert len(view.player_opened) == 2
    assert view.player_opened[-1][0] == view.rows[4].id

    controller.handle_command("cmd:n")
    assert not controller.auto_next
    controller.player_event("ended")
    assert len(view.player_opened) == 2  # 꺼진 뒤에는 다음 영상을 열지 않음


def test_auto_next_refused_when_not_played_from_list() -> None:
    controller, view = _make_app()
    controller.start()
    controller.handle_command("cmd:n")
    assert not controller.auto_next
    assert view.announcements[-1].startswith("다음 영상 자동 재생은")


def test_repeat_takes_priority_over_auto_next() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(0)
    controller.handle_command("cmd:t")
    controller.handle_command("cmd:n")
    controller.player_event("ended")
    assert ("restart", None) in view.player_calls
    assert len(view.player_opened) == 1


def test_auto_next_stops_at_last_row() -> None:
    controller, view = _make_app(total=3)
    controller.start()
    controller.play(2)
    controller.handle_command("cmd:n")
    controller.player_event("ended")
    assert len(view.player_opened) == 1
    assert "마지막 영상" in view.announcements[-1]


def test_speed_steps_between_quarter_and_double() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(0)
    controller.handle_player_key("speed_up")
    assert controller.playback_rate == 1.25
    assert ("set_rate", 1.25) in view.player_calls
    for _ in range(10):
        controller.handle_player_key("speed_up")
    assert controller.playback_rate == 2.0
    assert view.announcements[-1].startswith("재생 속도가 가장 빠릅니다")
    for _ in range(20):
        controller.handle_player_key("speed_down")
    assert controller.playback_rate == 0.25
    assert view.announcements[-1].startswith("재생 속도가 가장 느립니다")


def test_new_video_resets_speed_to_normal() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(0)
    controller.handle_player_key("speed_up")
    controller.play(1)
    assert controller.playback_rate == 1.0


def test_speed_shown_in_player_status() -> None:
    controller, view = _make_app()
    controller.start()
    controller.play(0)
    controller.handle_player_key("speed_down")
    assert "속도 0.75배" in view.player_status
