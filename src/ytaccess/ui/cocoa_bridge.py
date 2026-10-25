"""AppKit 전용 작은 도우미들 (macOS에서만 임포트됩니다).

보이스오버 공지, 클립보드, 폴더 선택 대화상자, 경고/입력 대화상자를
한 곳에 모아 Cocoa 화면 코드를 단순하게 유지합니다.
"""

from __future__ import annotations

from typing import Any

# NSAccessibility 관련 문자열 상수는 PyObjC 버전에 따라 노출 이름이 달라서
# getattr + 리터럴 폴백을 함께 사용합니다.
_AX_ANNOUNCEMENT = "AXAnnouncementRequested"
_AX_ANNOUNCEMENT_KEY = "AXAnnouncement"
_AX_PRIORITY_KEY = "AXPriority"


def _appkit() -> Any:
    import AppKit  # noqa: F401  (지연 임포트)
    return AppKit


def voiceover_announce(text: str, priority: str = "normal") -> None:
    """VoiceOver에게 공지를 요청합니다. 실패해도 예외를 밖으로 던지지 않습니다."""
    import AppKit

    note = getattr(AppKit, "NSAccessibilityAnnouncementRequestedNotification", _AX_ANNOUNCEMENT)
    key = getattr(AppKit, "NSAccessibilityAnnouncementKey", _AX_ANNOUNCEMENT_KEY)
    prio_key = getattr(AppKit, "NSAccessibilityPriorityKey", _AX_PRIORITY_KEY)
    prio = getattr(
        AppKit,
        "NSAccessibilityPriorityHigh" if priority == "high" else "NSAccessibilityPriorityMedium",
        90 if priority == "high" else 50,
    )
    info = {key: text, prio_key: prio}
    element = AppKit.NSApplication.sharedApplication()

    with_info = getattr(AppKit, "NSAccessibilityPostNotificationWithUserInfo", None)
    if with_info is not None:
        try:
            with_info(element, note, info)
            return
        except (TypeError, ValueError):
            pass

    post = getattr(AppKit, "NSAccessibilityPostNotification", None)
    if post is None:
        return
    try:
        post(element, note, info)
    except TypeError:
        try:
            post(element, note)
        except TypeError:
            pass


def copy_to_clipboard(text: str) -> bool:
    import AppKit

    pasteboard = AppKit.NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    paste_type = getattr(AppKit, "NSPasteboardTypeString", "NSStringPboardType")
    return bool(pasteboard.setString_forType_(text, paste_type))


def choose_folder(default_dir: str) -> str | None:
    """MP4를 저장할 폴더를 고르는 네이티브 대화상자 (보이스오버 완전 지원)."""
    import AppKit
    from Foundation import NSURL

    panel = AppKit.NSOpenPanel.openPanel()
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setCanCreateDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    panel.setResolvesAliases_(True)
    panel.setTitle_("MP4 파일을 저장할 폴더 선택")
    panel.setMessage_("선택한 폴더에 MP4 파일이 저장됩니다. '새 폴더' 버튼으로 폴더를 만들 수도 있습니다.")
    panel.setPrompt_("이 폴더에 저장")
    try:
        panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(default_dir)))
    except Exception:
        pass
    ok = getattr(AppKit, "NSModalResponseOK", 1)
    if panel.runModal() != ok:
        return None
    url = panel.URL()
    return str(url.path()) if url is not None else None


def show_alert(title: str, message: str) -> None:
    """오류를 음성뿐 아니라 표준 대화상자로도 알립니다."""
    import AppKit

    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message[:1000])
    alert.addButtonWithTitle_("확인")
    try:
        alert.setAlertStyle_(getattr(AppKit, "NSAlertStyleWarning", 0))
    except (TypeError, ValueError):
        pass
    alert.runModal()


def ask_text(title: str, message: str, default: str = "") -> str | None:
    """간단한 한 줄 입력 대화상자 (홈 검색어 변경용)."""
    import AppKit

    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(message)
    field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, 320, 26))
    field.setStringValue_(default)
    field.setBezeled_(True)
    field.setBezelStyle_(getattr(AppKit, "NSTextFieldSquareBezel", 0))
    field.setAccessibilityLabel_("새 홈 검색어")
    alert.setAccessoryView_(field)
    alert.addButtonWithTitle_("확인")
    alert.addButtonWithTitle_("취소")
    alert.window().setInitialFirstResponder_(field)
    first = getattr(AppKit, "NSAlertFirstButtonReturn", 1000)
    if alert.runModal() != first:
        return None
    return str(field.stringValue()).strip()


def reveal_in_finder(path: str) -> None:
    import AppKit
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    workspace = AppKit.NSWorkspace.sharedWorkspace()
    workspace.activateFileViewerSelectingURLs_([url])
