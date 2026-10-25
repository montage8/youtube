"""WKWebView + yt-player 재생 창.

* 로컬 HTTP 서버(127.0.0.1, 임의 포트)가 player.html / player.js /
  yt-player 번들을 제공합니다. macOS의 WKWebView는 IP 리터럴 루프백 HTTP를
  기본 허용하므로 App Transport Security 예외가 필요 없습니다.
* 페이지가 실패하면 JS를 HTML에 인라인한 뒤 https 베이스 URL로 재로드하는
  폴백이 있습니다.
* 모든 키보드 입력은 WKWebView 서브클래스가 가로채서 파이썬 컨트롤러로
  보냅니다. 따라서 보이스오버가 유튜브 iframe 내부를 헤맬 필요가 없습니다.
* JS -> 파이썬 통신은 WKScriptMessageHandler, 파이썬 -> JS 통신은
  evaluateJavaScript:completionHandler: (completionHandler 는 nil) 입니다.
  PyObjC 블록을 쓰지 않아 버전 호환성이 좋습니다.
"""

from __future__ import annotations

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import objc
import AppKit
from AppKit import NSMakeRect, NSMakeSize, NSViewHeightSizable, NSViewMaxYMargin, NSViewWidthSizable
from Foundation import NSObject, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration

# PyObjC / macOS SDK 버전에 따라 상수 이름이 다르므로 폴백을 둡니다.
NSWindow = AppKit.NSWindow
NSApplication = AppKit.NSApplication
_TITLED = getattr(AppKit, "NSWindowStyleMaskTitled", 1)
_CLOSABLE = getattr(AppKit, "NSWindowStyleMaskClosable", 2)
_MINIATURIZABLE = getattr(AppKit, "NSWindowStyleMaskMiniaturizable", 4)
_RESIZABLE = getattr(AppKit, "NSWindowStyleMaskResizable", 8)
_BACKING_BUFFERED = getattr(AppKit, "NSBackingStoreBuffered", 2)

from ..config import Config
from ..models import PlayerState, Video
from .base import normalize_key_action

RESOURCES = Path(__file__).resolve().parent.parent / "resources"
_PLAYER_HINT = (
    "동영상 재생 창. 숫자 0부터 9는 영상 길이의 0부터 90퍼센트 지점으로 이동, "
    "왼쪽 오른쪽 화살표는 5초 이동, 위 아래 화살표는 볼륨 조절, "
    "L은 현재 위치 읽기, 스페이스바는 재생과 일시정지, Esc는 닫기입니다."
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


class PlayerServer:
    """플레이어 정적 파일을 127.0.0.1의 빈 포트에서 제공합니다."""

    def __init__(self, root: Path = RESOURCES) -> None:
        handler = functools.partial(_QuietHandler, directory=str(root))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="ytaccess-player-http")
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/player.html"

    def shutdown(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


class _MessageHandler(NSObject):
    """window.webkit.messageHandlers.ytaccess.postMessage(...) 수신."""

    def userContentController_didReceiveScriptMessage_(self, _controller: Any, message: Any) -> None:
        owner: CocoaPlayerWindow | None = getattr(self, "owner", None)
        if owner is None:
            return
        try:
            body = message.body()
            data = json.loads(body) if isinstance(body, (str, bytes)) else dict(body)
            kind = data.get("type")
            if kind == "state":
                owner.on_state(PlayerState.from_mapping(data.get("state") or {}))
            elif kind == "event":
                owner.on_event(str(data.get("name") or ""), str(data.get("detail") or ""))
        except Exception:
            # JS에서 온 메시지 하나 때문에 앱이 죽으면 안 됩니다.
            return


class _NavigationDelegate(NSObject):
    def webView_didFinishNavigation_(self, _webView: Any, _navigation: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.on_page_loaded()

    def webView_didFailNavigation_withError_(self, _webView: Any, _navigation: Any, error: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.on_page_failed(str(error))

    def webView_didFailProvisionalNavigation_withError_(self, _webView: Any, _navigation: Any, error: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.on_page_failed(str(error))


class _WindowDelegate(NSObject):
    def windowShouldClose_(self, _window: Any) -> bool:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.on_close_button()
        return False  # 실제로 닫지 않고 숨깁니다(재사용).

    def windowDidBecomeKey_(self, _notification: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None:
            owner.on_focus()


class PlayerWebView(WKWebView):
    """모든 키 입력을 파이썬 컨트롤러로 넘기는 WKWebView."""

    def acceptsFirstResponder(self) -> bool:
        return True

    def keyDown_(self, event: Any) -> None:
        owner = getattr(self, "owner", None)
        if owner is not None and owner.handle_key(event):
            return
        objc.super(PlayerWebView, self).keyDown_(event)


class CocoaPlayerWindow:
    def __init__(self, config: Config, controller: Any) -> None:
        self.config = config
        self.controller = controller
        self.server = PlayerServer()
        self.state = PlayerState()
        self.visible = False
        self._pending: tuple[Video, str, str | None] | None = None
        self._page_ready = False
        self._page_failed = False
        self._used_inline_fallback = False
        self._window: Any = None
        self._webView: Any = None
        self._statusField: Any = None
        self._messageHandler: Any = None
        self._navigationDelegate: Any = None
        self._windowDelegate: Any = None
        self._build()

    # ------------------------------------------------------------------ 창 만들기
    def _build(self) -> None:
        rect = NSMakeRect(0, 0, 1000, 640)
        mask = _TITLED | _CLOSABLE | _MINIATURIZABLE | _RESIZABLE
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(rect, mask, _BACKING_BUFFERED, False)
        window.setTitle_("유튜브 재생")
        window.setMinSize_(NSMakeSize(640, 420))
        window.center()
        window.setReleasedWhenClosed_(False)
        window.setAccessibilityLabel_(_PLAYER_HINT)

        content = window.contentView()
        content.setAccessibilityLabel_(_PLAYER_HINT)

        configuration = WKWebViewConfiguration.alloc().init()
        try:
            configuration.preferences().setJavaScriptEnabled_(True)
        except Exception:
            pass
        try:  # WKAudiovisualMediaTypeNone: 사용자 동작 없이 자동 재생 허용
            configuration.setMediaTypesRequiringUserActionForPlayback_(0)
        except Exception:
            pass

        handler = _MessageHandler.alloc().init()
        handler.owner = self
        configuration.userContentController().addScriptMessageHandler_name_(handler, "ytaccess")

        web_rect = NSMakeRect(0, 34, 1000, 606)
        webView = PlayerWebView.alloc().initWithFrame_configuration_(web_rect, configuration)
        webView.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        webView.owner = self
        try:
            webView.setAccessibilityElement_(True)
            webView.setAccessibilityLabel_(_PLAYER_HINT)
            webView.setAccessibilityRoleDescription_("동영상 재생 화면")
        except Exception:
            pass

        navigation = _NavigationDelegate.alloc().init()
        navigation.owner = self
        webView.setNavigationDelegate_(navigation)

        from AppKit import NSTextField, NSFont

        status = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 1000, 34))
        status.setStringValue_("플레이어 준비 중…")
        status.setBezeled_(False)
        status.setDrawsBackground_(True)
        status.setEditable_(False)
        status.setSelectable_(False)
        status.setFont_(NSFont.boldSystemFontOfSize_(14))
        status.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        status.setAccessibilityLabel_("재생 상태. 플레이어 준비 중")
        status.setAccessibilityRoleDescription_("재생 상태")

        content.addSubview_(webView)
        content.addSubview_(status)

        delegate = _WindowDelegate.alloc().init()
        delegate.owner = self
        window.setDelegate_(delegate)

        self._window = window
        self._webView = webView
        self._statusField = status
        self._messageHandler = handler
        self._navigationDelegate = navigation
        self._windowDelegate = delegate

    # ------------------------------------------------------------------ 열기/닫기
    def open(self, video: Video, engine: str, stream_url: str | None = None) -> None:
        self._pending = (video, engine, stream_url)
        self._page_ready = False
        self._page_failed = False
        self.state = PlayerState(title=video.title, engine=engine, playback="loading", volume=self.config.start_volume)
        self._window.setTitle_(f"재생: {video.title}")
        self._window.setAccessibilityLabel_(f"{video.title} 재생 중. {_PLAYER_HINT}")
        self._window.contentView().setAccessibilityLabel_(f"{video.title} 재생 중. {_PLAYER_HINT}")
        self.set_status(f"{video.title} · 재생 준비 중")
        self._load_page()
        self._window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._window.makeFirstResponder_(self._webView)
        self.visible = True
        self.controller.set_player_state(self.state)

    def _load_page(self) -> None:
        if self._used_inline_fallback:
            self._load_inline_fallback()
            return
        url = NSURL.URLWithString_(self.server.url)
        request = NSURLRequest.requestWithURL_(url)
        self._webView.loadRequest_(request)

    def _load_inline_fallback(self) -> None:
        try:
            html = (RESOURCES / "player.html").read_text(encoding="utf-8")
            vendor = (RESOURCES / "vendor" / "yt-player.js").read_text(encoding="utf-8")
            bridge = (RESOURCES / "player.js").read_text(encoding="utf-8")
            html = html.replace(
                '<script src="vendor/yt-player.js"></script>',
                "<script>" + vendor.replace("</script>", "<\\/script>") + "</script>",
            )
            html = html.replace(
                '<script src="player.js"></script>',
                "<script>" + bridge.replace("</script>", "<\\/script>") + "</script>",
            )
            self._webView.loadHTMLString_baseURL_(html, NSURL.URLWithString_("https://ytaccess.local/"))
        except Exception:
            pass

    def close(self) -> None:
        self.eval_js("if (window.YTACCESS) window.YTACCESS.stop();")
        self._window.orderOut_(None)
        self.visible = False
        self._page_ready = False
        self._pending = None

    def shutdown(self) -> None:
        self.close()
        self.server.shutdown()

    # ------------------------------------------------------------------ JS -> Python
    def on_page_loaded(self) -> None:
        self._page_ready = True
        self._start_pending()

    def on_page_failed(self, error: str) -> None:
        if not self._used_inline_fallback:
            self._used_inline_fallback = True
            self._page_failed = True
            self._load_inline_fallback()
            return
        self.controller.player_event("error", f"플레이어 페이지를 불러오지 못했습니다: {error[:200]}")

    def _start_pending(self) -> None:
        if not self._pending or not self._page_ready:
            return
        video, engine, stream_url = self._pending
        title = json.dumps(video.title, ensure_ascii=False)
        if engine == "adfree" and stream_url:
            js = f"window.YTACCESS.startNative({json.dumps(stream_url)}, {title});"
        else:
            js = f"window.YTACCESS.startYTPlayer({json.dumps(video.id)}, {title});"
        self.eval_js(js)
        self.eval_js(f"window.YTACCESS.setVolume({int(self.config.start_volume)});")
        self._pending = None

    def on_state(self, state: PlayerState) -> None:
        state.title = state.title or self.state.title or "재생 중"
        self.state = state
        self.controller.set_player_state(state)

    def on_event(self, name: str, detail: str = "") -> None:
        self.controller.player_event(name, detail)

    def on_close_button(self) -> None:
        self.controller.handle_player_key("escape")

    def on_focus(self) -> None:
        try:
            self._window.makeFirstResponder_(self._webView)
        except Exception:
            pass

    # ------------------------------------------------------------------ Python -> JS
    def eval_js(self, script: str) -> None:
        if self._webView is None:
            return
        try:
            self._webView.evaluateJavaScript_completionHandler_(script, None)
        except Exception:
            pass

    def handle_key(self, event: Any) -> bool:
        chars = event.charactersIgnoringModifiers() or ""
        cmd_mask = getattr(AppKit, "NSEventModifierFlagCommand", None) or getattr(AppKit, "NSCommandKeyMask", 1 << 20)
        try:
            command = bool(event.modifierFlags() & cmd_mask)
        except Exception:
            command = False
        action = normalize_key_action(str(chars), int(event.keyCode()), command)
        if not action:
            return False
        if action.startswith("cmd:"):
            if self.controller.handle_command(action):
                return True
            if action == "cmd:w":
                return self.controller.handle_player_key("escape")
            return False
        return self.controller.handle_player_key(action)

    # ------------------------------------------------------------------ View API
    def set_status(self, text: str) -> None:
        if self._statusField is None:
            return
        self._statusField.setStringValue_(text)
        self._statusField.setAccessibilityLabel_("재생 상태. " + text)

    def player_state(self) -> PlayerState:
        return self.state

    def player_seek(self, seconds: float) -> None:
        self.eval_js(f"window.YTACCESS.seek({float(seconds):.3f});")

    def player_seek_percent(self, percent: float) -> None:
        self.eval_js(f"window.YTACCESS.seekPercent({float(percent):.2f});")

    def player_seek_relative(self, delta: float) -> None:
        self.eval_js(f"window.YTACCESS.seekRelative({float(delta):.3f});")
        self.state.current_time = max(0.0, self.state.current_time + float(delta))

    def player_set_volume(self, value: float) -> None:
        self.eval_js(f"window.YTACCESS.setVolume({float(value):.2f});")

    def player_change_volume(self, delta: float) -> None:
        self.eval_js(f"window.YTACCESS.changeVolume({float(delta):.2f});")
        self.state.volume = min(100.0, max(0.0, self.state.volume + float(delta)))

    def player_toggle(self) -> None:
        self.eval_js("window.YTACCESS.toggle();")

    def player_mute(self) -> None:
        self.eval_js("window.YTACCESS.muteToggle();")

    def player_restart(self) -> None:
        self.eval_js("window.YTACCESS.restart();")

    def player_close(self) -> None:
        self.close()
