"""macOS 네이티브(Cocoa/AppKit) 화면.

보이스오버 친화 설계 요약
--------------------------
* 모든 컨트롤이 네이티브 AppKit 객체입니다. NSTableView, NSSearchField,
  NSButton, NSMenu 는 macOS 접근성(AX) 트리를 그대로 제공합니다.
* 표의 각 행에는 "1번, 전체 50개 중, 제목, 채널, 길이 10분 23초, ..." 처럼
  보이스오버가 한 번에 읽을 수 있는 완전한 문장 레이블을 붙입니다.
* 모든 명령이 메뉴에도 등장합니다. (보이스오버 사용자는 VO+M 으로 메뉴를 탐색)
* 상태 변화(검색 완료, 추가 로딩, 다운로드 진행 등)는 음성 공지로 알립니다.
* 재생 창은 WKWebView를 단일 접근성 요소로 취급해 유튜브 iframe 내부의
  복잡한 웹 접근성 트리를 보이스오버가 헤매지 않게 합니다.
"""

from __future__ import annotations

import queue
import traceback
from typing import Any, Callable

import objc
import AppKit
import Foundation
from Foundation import NSIndexSet, NSObject, NSRunLoop

_COMMON_MODES = getattr(Foundation, "NSRunLoopCommonModes", "kCFRunLoopCommonModes")
_BACKING_BUFFERED = getattr(AppKit, "NSBackingStoreBuffered", 2)

from .. import formatting
from ..config import Config
from ..controller import AppController
from ..models import PlayerState, SortMode, Video
from ..speech import Announcer
from . import cocoa_bridge
from .base import SHORTCUT_HELP, View, normalize_key_action

# 버전 호환용 상수
_TITLED = getattr(AppKit, "NSWindowStyleMaskTitled", 1)
_CLOSABLE = getattr(AppKit, "NSWindowStyleMaskClosable", 2)
_MINIATURIZABLE = getattr(AppKit, "NSWindowStyleMaskMiniaturizable", 4)
_RESIZABLE = getattr(AppKit, "NSWindowStyleMaskResizable", 8)
_REGULAR_POLICY = getattr(AppKit, "NSApplicationActivationPolicyRegular", 0)
_WIDTH_SIZABLE = getattr(AppKit, "NSViewWidthSizable", 2)
_HEIGHT_SIZABLE = getattr(AppKit, "NSViewHeightSizable", 16)
_MAX_Y_MARGIN = getattr(AppKit, "NSViewMaxYMargin", 8)
_MIN_X_MARGIN = getattr(AppKit, "NSViewMinXMargin", 4)
_TRUNCATING_TAIL = getattr(AppKit, "NSLineBreakByTruncatingTail", 4)
_TABLE_AUTORESIZE = getattr(AppKit, "NSTableColumnAutoresizingMask", 1)
_ROUNDED_BEZEL = getattr(AppKit, "NSBezelStyleRounded", 1)

_TABLE_HELP = (
    "동영상 목록 표입니다. 위아래 화살표로 이동하고 엔터 키 또는 이중 클릭으로 재생합니다. "
    "Command+F는 검색, Command+L은 링크 복사, Command+D는 MP4 다운로드입니다. "
    "표 끝에 가까워지면 동영상 50개를 자동으로 더 불러옵니다."
)


# --------------------------------------------------------------------------- 스레드 → 메인 스레드
class _TimerTarget(NSObject):
    def tick_(self, _timer: Any) -> None:
        dispatcher = getattr(self, "dispatcher", None)
        if dispatcher is not None:
            dispatcher.drain()


class MainThreadDispatcher:
    """백그라운드 스레드의 화면 갱신을 0.05초 타이머로 메인 스레드에서 실행."""

    def __init__(self) -> None:
        self.queue: queue.Queue[Callable[[], None]] = queue.Queue()
        target = _TimerTarget.alloc().init()
        target.dispatcher = self
        self.target = target
        self.timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05, target, "tick:", None, True
        )
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, _COMMON_MODES)

    def post(self, fn: Callable[[], None]) -> None:
        self.queue.put(fn)

    def drain(self) -> None:
        while True:
            try:
                fn = self.queue.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception:
                traceback.print_exc()


# --------------------------------------------------------------------------- 표 데이터 소스
class _TableDataSource(NSObject):
    def numberOfRowsInTableView_(self, _tableView: Any) -> int:
        owner = getattr(self, "owner", None)
        return len(owner.rows) if owner else 0

    def tableView_viewForTableColumn_row_(self, tableView: Any, _column: Any, row: int) -> Any:
        owner = getattr(self, "owner", None)
        if owner is None or not (0 <= row < len(owner.rows)):
            return None
        cell = tableView.makeViewWithIdentifier_owner_("VideoCell", self)
        if cell is None:
            cell = AppKit.NSTableCellView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 940, 28))
            cell.setIdentifier_("VideoCell")
            field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(8, 3, 924, 22))
            field.setBezeled_(False)
            field.setDrawsBackground_(False)
            field.setEditable_(False)
            field.setSelectable_(False)
            field.setLineBreakMode_(_TRUNCATING_TAIL)
            field.setFont_(AppKit.NSFont.systemFontOfSize_(13))
            cell.addSubview_(field)
            cell.setTextField_(field)
        field = cell.textField()
        field.setStringValue_(owner.row_display(row))
        spoken = owner.row_spoken(row)
        try:
            cell.setAccessibilityElement_(True)
            cell.setAccessibilityLabel_(spoken)
            cell.setAccessibilityRoleDescription_("동영상 항목")
            field.setAccessibilityLabel_(spoken)
        except Exception:
            pass
        return cell

    def tableViewSelectionDidChange_(self, _notification: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is None or owner.controller is None:
            return
        index = owner.table.selectedRow()
        if index >= 0:
            owner.controller.row_selected(index)


class TableView(AppKit.NSTableView):
    def keyDown_(self, event: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            action = owner.key_action(event)
            if action == "return":
                owner.controller.play()
                return
            if action and action.startswith("cmd:"):
                if owner.controller.handle_command(action):
                    return
        objc.super(TableView, self).keyDown_(event)


class SearchField(AppKit.NSSearchField):
    def keyDown_(self, event: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None and owner.key_action(event) == "escape":
            owner.focus_table()
            owner.view_announce("검색을 취소하고 표로 돌아왔습니다.")
            return
        objc.super(SearchField, self).keyDown_(event)


# --------------------------------------------------------------------------- 메뉴 동작
class _MenuActions(NSObject):
    def performSearch_(self, _sender: Any) -> None:
        v = self.view
        v.controller.search(str(v.search.stringValue()).strip())

    def playSelected_(self, _sender: Any) -> None:
        self.view.controller.play()

    def searchMenuItem_(self, _sender: Any) -> None:
        self.view.focus_search()

    def playMenuItem_(self, _sender: Any) -> None:
        self.view.controller.play()

    def copyLinkMenuItem_(self, _sender: Any) -> None:
        self.view.controller.copy_link()

    def downloadMenuItem_(self, _sender: Any) -> None:
        self.view.controller.download()

    def loadMoreMenuItem_(self, _sender: Any) -> None:
        self.view.controller.load_more()

    def refreshMenuItem_(self, _sender: Any) -> None:
        self.view.controller.refresh()

    def homeMenuItem_(self, _sender: Any) -> None:
        self.view.controller.home_feed()

    def sortLatestMenuItem_(self, _sender: Any) -> None:
        self.view.controller.set_sort("latest")

    def sortRelevanceMenuItem_(self, _sender: Any) -> None:
        self.view.controller.set_sort("relevance")

    def homeQueryMenuItem_(self, _sender: Any) -> None:
        self.view.change_home_query()

    def engineMenuItem_(self, _sender: Any) -> None:
        self.view.toggle_engine()

    def helpMenuItem_(self, _sender: Any) -> None:
        self.view.show_help()

    def aboutMenuItem_(self, _sender: Any) -> None:
        self.view.show_about()

    def quitMenuItem_(self, _sender: Any) -> None:
        AppKit.NSApplication.sharedApplication().terminate_(None)

    def playerCloseMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("escape")

    def playerTimeMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("time")

    def playerSeekMenuItem_(self, sender: Any) -> None:
        percent = int(sender.tag())
        self.view.controller.handle_player_key(f"digit:{percent // 10}")

    def playerBackMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("left")

    def playerForwardMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("right")

    def playerVolumeUpMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("up")

    def playerVolumeDownMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("down")

    def playerToggleMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("space")

    def playerMuteMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_player_key("mute")

    def playerRepeatMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_command("cmd:t")

    def playerAutoNextMenuItem_(self, _sender: Any) -> None:
        self.view.controller.handle_command("cmd:n")


class _AppDelegate(NSObject):
    def applicationShouldTerminateAfterLastWindowClosed_(self, _app: Any) -> bool:
        return True

    def applicationWillTerminate_(self, _notification: Any) -> None:
        view = getattr(self, "view", None)
        if view is not None:
            view.shutdown()


def _item(title: str, action: str | None, key: str, target: Any, tag: int = 0) -> Any:
    item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
    if action:
        item.setTarget_(target)
    if tag:
        item.setTag_(tag)
    return item


def build_main_menu(actions: _MenuActions) -> None:
    main = AppKit.NSMenu.alloc().init()

    # 앱 메뉴
    app_item = _item("유튜브 접근성", None, "", actions)
    app_menu = AppKit.NSMenu.alloc().initWithTitle_("유튜브 접근성")
    app_menu.addItem_(_item("이 프로그램에 관하여", "aboutMenuItem:", "", actions))
    app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    app_menu.addItem_(_item("홈 검색어 변경…", "homeQueryMenuItem:", ",", actions))
    app_menu.addItem_(_item("재생 엔진 전환 (yt-player ↔ 광고 없는 재생)", "engineMenuItem:", "", actions))
    app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    app_menu.addItem_(_item("키보드 단축키 안내", "helpMenuItem:", "/", actions))
    app_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    app_menu.addItem_(_item("종료", "quitMenuItem:", "q", actions))
    app_item.setSubmenu_(app_menu)
    main.addItem_(app_item)

    # 동영상 메뉴
    video_item = _item("동영상", None, "", actions)
    video_menu = AppKit.NSMenu.alloc().initWithTitle_("동영상")
    video_menu.addItem_(_item("검색…", "searchMenuItem:", "f", actions))
    video_menu.addItem_(_item("선택한 동영상 재생", "playMenuItem:", "", actions))
    video_menu.addItem_(_item("링크 복사", "copyLinkMenuItem:", "l", actions))
    video_menu.addItem_(_item("MP4로 다운로드…", "downloadMenuItem:", "d", actions))
    video_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    video_menu.addItem_(_item("동영상 50개 더 보기", "loadMoreMenuItem:", "e", actions))
    video_menu.addItem_(_item("새로고침", "refreshMenuItem:", "r", actions))
    video_menu.addItem_(_item("홈 (최신순 동영상)", "homeMenuItem:", "0", actions))
    video_menu.addItem_(AppKit.NSMenuItem.separatorItem())
    video_menu.addItem_(_item("최신순으로 정렬", "sortLatestMenuItem:", "1", actions))
    video_menu.addItem_(_item("관련도순으로 정렬", "sortRelevanceMenuItem:", "2", actions))
    video_item.setSubmenu_(video_menu)
    main.addItem_(video_item)

    # 재생 메뉴 (메뉴로도 모든 재생 조작 가능)
    player_item = _item("재생", None, "", actions)
    player_menu = AppKit.NSMenu.alloc().initWithTitle_("재생")
    player_menu.addItem_(_item("재생 창 닫기 (Esc)", "playerCloseMenuItem:", "", actions))
    player_menu.addItem_(_item("현재 위치 음성으로 듣기 (L)", "playerTimeMenuItem:", "", actions))
    player_menu.addItem_(_item("재생 / 일시정지", "playerToggleMenuItem:", "", actions))
    player_menu.addItem_(_item("음소거 켜기 / 끄기", "playerMuteMenuItem:", "", actions))
    player_menu.addItem_(_item("연속 반복 켜기 / 끄기 (⌘T)", "playerRepeatMenuItem:", "t", actions))
    player_menu.addItem_(_item("다음 영상 자동 재생 켜기 / 끄기 (⌘N)", "playerAutoNextMenuItem:", "n", actions))
    seek_item = _item("위치 이동", None, "", actions)
    seek_menu = AppKit.NSMenu.alloc().initWithTitle_("위치 이동")
    for percent in range(0, 100, 10):
        label = "처음으로 (0%)" if percent == 0 else f"{percent}% 지점으로"
        seek_menu.addItem_(_item(label, "playerSeekMenuItem:", "", actions, tag=percent))
    seek_item.setSubmenu_(seek_menu)
    player_menu.addItem_(seek_item)
    player_menu.addItem_(_item("5초 뒤로", "playerBackMenuItem:", "", actions))
    player_menu.addItem_(_item("5초 앞으로", "playerForwardMenuItem:", "", actions))
    player_menu.addItem_(_item("볼륨 올리기", "playerVolumeUpMenuItem:", "", actions))
    player_menu.addItem_(_item("볼륨 내리기", "playerVolumeDownMenuItem:", "", actions))
    player_item.setSubmenu_(player_menu)
    main.addItem_(player_item)

    # 도움말 메뉴
    help_item = _item("도움말", None, "", actions)
    help_menu = AppKit.NSMenu.alloc().initWithTitle_("도움말")
    help_menu.addItem_(_item("키보드 단축키 안내", "helpMenuItem:", "", actions))
    help_item.setSubmenu_(help_menu)
    main.addItem_(help_item)

    AppKit.NSApplication.sharedApplication().setMainMenu_(main)


# --------------------------------------------------------------------------- 화면
class CocoaView(View):
    def __init__(self, config: Config, announcer: Announcer) -> None:
        self.config = config
        self.announcer = announcer
        self.controller: AppController | None = None
        self.player: Any = None
        self.rows: list[Video] = []
        self._last_first_id: str | None = None
        self.dispatcher: MainThreadDispatcher | None = None
        self.actions = _MenuActions.alloc().init()
        self.actions.view = self
        self.dataSource = _TableDataSource.alloc().init()
        self.dataSource.owner = self
        self.window: Any = None
        self.table: Any = None
        self.search: Any = None
        self.status: Any = None
        self.help_window: Any = None

    # ------------------------------------------------------------------ UI 구성
    def build(self) -> None:
        self.dispatcher = MainThreadDispatcher()
        rect = AppKit.NSMakeRect(0, 0, 1000, 720)
        mask = _TITLED | _CLOSABLE | _MINIATURIZABLE | _RESIZABLE
        window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(rect, mask, _BACKING_BUFFERED, False)
        window.setTitle_("유튜브 접근성 — ytaccess")
        window.setMinSize_(AppKit.NSMakeSize(760, 480))
        window.center()
        window.setFrameAutosaveName_("ytaccess-main")
        window.setReleasedWhenClosed_(False)
        content = window.contentView()
        content.setAccessibilityLabel_("유튜브 동영상 목록 창")

        # 검색창
        search = SearchField.alloc().initWithFrame_(AppKit.NSMakeRect(20, 676, 590, 30))
        search.setPlaceholderString_("검색어 입력 후 엔터")
        search.setFont_(AppKit.NSFont.systemFontOfSize_(15))
        search.setTarget_(self.actions)
        search.setAction_("performSearch:")
        search.setAutoresizingMask_(_WIDTH_SIZABLE | _MAX_Y_MARGIN)
        search.setAccessibilityLabel_("검색어 입력. 검색어를 입력하고 엔터 키를 누르면 검색합니다.")
        search.setAccessibilityHelp_("Command+F 를 누르면 이 검색창으로 이동합니다. Esc 를 누르면 표로 돌아갑니다.")
        search.owner = self
        content.addSubview_(search)

        self._add_button(content, "검색", 620, 80, "performSearch:", "검색어를 입력한 뒤 이 버튼을 누르거나 엔터 키를 누릅니다.")
        self._add_button(content, "재생", 710, 80, "playMenuItem:", "선택한 동영상을 yt-player로 재생합니다.")
        self._add_button(content, "더 보기", 800, 90, "loadMoreMenuItem:", "동영상을 50개 더 불러옵니다.")
        self._add_button(content, "새로고침", 900, 80, "refreshMenuItem:", "현재 목록을 다시 불러옵니다.")

        # 표
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(20, 62, 960, 604))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutoresizingMask_(_WIDTH_SIZABLE | _HEIGHT_SIZABLE)
        table = TableView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 940, 604))
        table.owner = self
        column = AppKit.NSTableColumn.alloc().initWithIdentifier_("videos")
        column.setWidth_(940)
        column.setResizingMask_(_TABLE_AUTORESIZE)
        column.headerCell().setStringValue_("동영상")
        table.addTableColumn_(column)
        table.setHeaderView_(None)
        table.setRowHeight_(28)
        table.setDataSource_(self.dataSource)
        table.setDelegate_(self.dataSource)
        table.setTarget_(self.actions)
        table.setDoubleAction_("playSelected:")
        table.setAllowsMultipleSelection_(False)
        table.setAllowsEmptySelection_(False)
        table.setUsesAlternatingRowBackgroundColors_(True)
        table.setAccessibilityLabel_("동영상 목록 표")
        table.setAccessibilityHelp_(_TABLE_HELP)
        scroll.setDocumentView_(table)
        content.addSubview_(scroll)

        # 상태 표시줄
        status = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(20, 18, 960, 36))
        status.setStringValue_("동영상을 불러오는 중입니다…")
        status.setBezeled_(False)
        status.setDrawsBackground_(False)
        status.setEditable_(False)
        status.setSelectable_(False)
        status.setLineBreakMode_(_TRUNCATING_TAIL)
        status.setFont_(AppKit.NSFont.boldSystemFontOfSize_(14))
        status.setAutoresizingMask_(_WIDTH_SIZABLE | _MAX_Y_MARGIN)
        status.setAccessibilityRoleDescription_("상태")
        status.setAccessibilityLabel_("상태. 동영상을 불러오는 중입니다")
        content.addSubview_(status)

        self.window = window
        self.table = table
        self.search = search
        self.status = status

    def _add_button(self, content: Any, title: str, x: int, width: int, action: str, label: str) -> None:
        button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(x, 672, width, 34))
        button.setTitle_(title)
        try:
            button.setBezelStyle_(_ROUNDED_BEZEL)
        except (TypeError, ValueError):
            pass
        button.setTarget_(self.actions)
        button.setAction_(action)
        button.setAutoresizingMask_(_MIN_X_MARGIN | _MAX_Y_MARGIN)
        button.setToolTip_(label)
        button.setAccessibilityLabel_(f"{title} 버튼. {label}")
        content.addSubview_(button)

    def show(self) -> None:
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self.table)

    def attach_controller(self, controller: AppController) -> None:
        self.controller = controller

    def attach_player(self, player: Any) -> None:
        self.player = player

    def shutdown(self) -> None:
        if self.controller:
            self.controller.close()
        if self.player:
            self.player.shutdown()

    # ------------------------------------------------------------------ 키/도우미
    def key_action(self, event: Any) -> str | None:
        chars = event.charactersIgnoringModifiers() or ""
        cmd_mask = getattr(AppKit, "NSEventModifierFlagCommand", None) or getattr(AppKit, "NSCommandKeyMask", 1 << 20)
        try:
            command = bool(event.modifierFlags() & cmd_mask)
        except Exception:
            command = False
        return normalize_key_action(str(chars), int(event.keyCode()), command)

    def row_display(self, index: int) -> str:
        if 0 <= index < len(self.rows):
            return formatting.row_display(index, self.rows[index])
        return ""

    def row_spoken(self, index: int) -> str:
        if 0 <= index < len(self.rows):
            return formatting.row_spoken(index, self.rows[index], len(self.rows))
        return ""

    def view_announce(self, text: str, priority: str = "normal") -> None:
        self.announcer.speak(text, priority)

    # ------------------------------------------------------------------ View API
    def set_rows(self, videos: list[Video], title: str, mode: SortMode, query: str, home: bool) -> None:
        first = videos[0].id if videos else None
        replaced = first != self._last_first_id
        self._last_first_id = first
        self.rows = list(videos)
        self.table.reloadData()
        if self.rows:
            index = self.table.selectedRow()
            if replaced or index < 0 or index >= len(self.rows):
                self.table.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(0), False)
                self.table.scrollRowToVisible_(0)
        self.window.setTitle_(f"{title} — ytaccess")
        self.status.setAccessibilityLabel_("상태. " + (self.status.stringValue() or ""))

    def set_status(self, text: str, announce: bool = False) -> None:
        self.status.setStringValue_(text)
        self.status.setAccessibilityLabel_("상태. " + text)
        if announce:
            self.view_announce(text)

    def focus_table(self) -> None:
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.table)

    def focus_search(self) -> None:
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.search)
        self.view_announce("검색어를 입력한 뒤 엔터 키를 누르세요.")

    def selected_index(self) -> int:
        index = self.table.selectedRow()
        return index if index >= 0 else 0

    def announce(self, text: str, priority: str = "normal") -> None:
        self.view_announce(text, priority)

    def show_error(self, title: str, message: str) -> None:
        self.view_announce(f"{title}. {message}", "high")
        try:
            cocoa_bridge.show_alert(title, message)
        except Exception:
            pass

    def copy_to_clipboard(self, text: str) -> None:
        cocoa_bridge.copy_to_clipboard(text)

    def choose_download_folder(self) -> str | None:
        return cocoa_bridge.choose_folder(str(self.config.download_path))

    def run_on_main(self, fn: Callable[[], None]) -> None:
        if self.dispatcher:
            self.dispatcher.post(fn)
        else:
            fn()

    # ---- 플레이어 위임 ----
    def open_player(self, video: Video, engine: str, stream_url: str | None = None) -> None:
        if self.player:
            self.player.open(video, engine, stream_url)

    def close_player(self) -> None:
        if self.player:
            self.player.close()

    def set_player_status(self, text: str) -> None:
        if self.player:
            self.player.set_status(text)

    def player_state(self) -> PlayerState:
        return self.player.player_state() if self.player else PlayerState()

    def player_seek(self, seconds: float) -> None:
        if self.player:
            self.player.player_seek(seconds)

    def player_seek_percent(self, percent: float) -> None:
        if self.player:
            self.player.player_seek_percent(percent)

    def player_seek_relative(self, delta: float) -> None:
        if self.player:
            self.player.player_seek_relative(delta)

    def player_set_volume(self, value: float) -> None:
        if self.player:
            self.player.player_set_volume(value)

    def player_change_volume(self, delta: float) -> None:
        if self.player:
            self.player.player_change_volume(delta)

    def player_toggle(self) -> None:
        if self.player:
            self.player.player_toggle()

    def player_mute(self) -> None:
        if self.player:
            self.player.player_mute()

    def player_restart(self) -> None:
        if self.player:
            self.player.player_restart()

    # ------------------------------------------------------------------ 대화상자
    def change_home_query(self) -> None:
        answer = cocoa_bridge.ask_text(
            "홈 검색어 변경",
            "앱을 켰을 때 최신순으로 보여줄 검색어를 입력하세요. 인기 급상승을 원하면 '인기'라고 입력하세요.",
            self.config.home_query,
        )
        if answer is None:
            self.view_announce("홈 검색어 변경을 취소했습니다.")
            return
        if answer.strip() in ("인기", "trending", "인기 급상승"):
            self.config.home_mode = "trending"
            self.config.save()
            self.view_announce("홈 화면을 인기 급상승 동영상으로 변경했습니다.")
            if self.controller:
                self.controller.home_feed()
            return
        self.config.home_mode = "latest"
        if self.controller:
            self.controller.set_home_query(answer)

    def toggle_engine(self) -> None:
        new = "adfree" if self.config.player_engine == "ytplayer" else "ytplayer"
        if self.controller:
            self.controller.set_engine(new)

    def show_about(self) -> None:
        cocoa_bridge.show_alert(
            "유튜브 접근성 (ytaccess)",
            "보이스오버 사용자를 위한 광고 없는 유튜브 탐색·재생·다운로드 프로그램입니다. "
            "검색과 다운로드는 yt-dlp, 재생은 yt-player(또는 yt-dlp 직접 스트림)를 사용합니다. "
            "자세한 내용은 README.md와 키보드 단축키 안내를 참고하세요.",
        )

    def show_help(self) -> None:
        if self.help_window is None:
            rect = AppKit.NSMakeRect(0, 0, 720, 620)
            mask = _TITLED | _CLOSABLE | _RESIZABLE
            window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(rect, mask, _BACKING_BUFFERED, False)
            window.setTitle_("키보드 단축키 안내")
            window.center()
            window.setReleasedWhenClosed_(False)
            scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 720, 620))
            scroll.setHasVerticalScroller_(True)
            scroll.setAutoresizingMask_(_WIDTH_SIZABLE | _HEIGHT_SIZABLE)
            text = AppKit.NSTextView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 700, 620))
            text.setString_(SHORTCUT_HELP)
            text.setEditable_(False)
            text.setRichText_(False)
            text.setFont_(AppKit.NSFont.systemFontOfSize_(15))
            text.setAccessibilityLabel_("키보드 단축키 안내")
            scroll.setDocumentView_(text)
            window.contentView().addSubview_(scroll)
            self.help_window = window
        self.help_window.makeKeyAndOrderFront_(None)


def run_cocoa(config: Config, backend: Any, announcer: Announcer, demo: bool = False) -> int:
    from PyObjCTools import AppHelper

    from .cocoa_player import CocoaPlayerWindow

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(_REGULAR_POLICY)

    view = CocoaView(config, announcer)
    view.build()
    controller = AppController(config, backend, view, announcer)
    view.attach_controller(controller)
    view.attach_player(CocoaPlayerWindow(config, controller))

    delegate = _AppDelegate.alloc().init()
    delegate.view = view
    app.setDelegate_(delegate)
    build_main_menu(view.actions)

    view.show()
    controller.start()
    AppHelper.runEventLoop()
    return 0
