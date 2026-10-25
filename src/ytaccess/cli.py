"""명령행 진입점.

    python -m ytaccess                  macOS 네이티브 창 실행
    python -m ytaccess --demo          인터넷 없이 가짜 데이터로 UI 시험
    python -m ytaccess --terminal      터미널 모드
    python -m ytaccess --doctor        설치 상태 진단
    python -m ytaccess --self-test     로직 자체 점검
"""

from __future__ import annotations

import argparse
import importlib.util
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .config import Config, default_config_path, default_download_dir
from .demo_backend import DemoBackend
from .speech import Announcer, is_voiceover_running


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytaccess",
        description="보이스오버 사용자를 위한 macOS 유튜브 탐색·재생·다운로드 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python -m ytaccess                       # 일반 실행\n"
            "  python -m ytaccess --demo                # 오프라인 UI 시험\n"
            "  python -m ytaccess --engine adfree       # 광고 없는 직접 재생\n"
            "  python -m ytaccess --doctor              # 설치 진단\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ytaccess {__version__}")
    parser.add_argument("--terminal", "-t", action="store_true", help="Cocoa 창 대신 터미널 모드로 실행")
    parser.add_argument("--demo", action="store_true", help="실제 유튜브 대신 가짜 데이터 사용(오프라인 시험)")
    parser.add_argument("--doctor", action="store_true", help="설치 상태를 진단하고 종료")
    parser.add_argument("--self-test", action="store_true", help="핵심 로직을 점검하고 종료")
    parser.add_argument("--config", metavar="PATH", help="설정 파일 경로 (기본: ~/Library/Application Support/ytaccess/settings.json)")
    parser.add_argument("--save-config", action="store_true", help="이번 명령행 옵션을 설정 파일에 저장")

    parser.add_argument("--engine", choices=["ytplayer", "adfree"], help="재생 엔진")
    parser.add_argument("--home-query", metavar="TEXT", help="처음 켰을 때 최신순으로 보여줄 검색어")
    parser.add_argument("--home-mode", choices=["latest", "trending"], help="홈 피드 종류")
    parser.add_argument("--sort", choices=["relevance", "latest"], help="검색 결과 정렬")
    parser.add_argument("--page-size", type=int, metavar="N", help="한 번에 확장할 동영상 수 (기본 50)")
    parser.add_argument("--speech", choices=["auto", "voiceover", "say", "both", "off"], help="음성 안내 방식")
    parser.add_argument("--voice", metavar="NAME", help="say 에서 사용할 macOS 음성 이름")
    parser.add_argument("--download-dir", metavar="PATH", help="MP4 기본 저장 폴더")
    parser.add_argument("--download-subtitles", action="store_true", help="자막도 함께 다운로드")
    parser.add_argument("--cookies-from-browser", metavar="NAME", help="연령 제한 영상용 쿠키 (safari, chrome …)")
    return parser


def apply_overrides(config: Config, args: argparse.Namespace) -> None:
    mapping = {
        "engine": "player_engine",
        "home_query": "home_query",
        "home_mode": "home_mode",
        "sort": "search_sort",
        "page_size": "page_size",
        "speech": "speech_mode",
        "voice": "speech_voice",
        "download_dir": "download_dir",
        "cookies_from_browser": "cookies_from_browser",
    }
    for arg_name, config_name in mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            setattr(config, config_name, value)
    if args.download_subtitles:
        config.download_subtitles = True
    config.validate()


def make_backend(config: Config, demo: bool) -> Any:
    if demo:
        return DemoBackend()
    from .backend import YtDlpBackend

    return YtDlpBackend(
        language=config.language,
        region=config.region,
        cookies_from_browser=config.cookies_from_browser,
        download_subtitles=config.download_subtitles,
    )


def make_announcer(config: Config) -> Announcer:
    hook = None
    if sys.platform == "darwin":
        try:
            from .ui.cocoa_bridge import voiceover_announce

            hook = voiceover_announce
        except Exception:
            hook = None
    return Announcer(config, voiceover_hook=hook, voiceover_detector=is_voiceover_running)


# --------------------------------------------------------------------------- 진단
def run_doctor(config: Config) -> int:
    from .config import default_config_path

    print("=" * 66)
    print(" ytaccess 설치 진단")
    print("=" * 66)
    print(f"운영체제        : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"파이썬          : {sys.version.split()[0]} ({sys.executable})")
    print(f"설정 파일       : {default_config_path()} (존재: {default_config_path().exists()})")
    print(f"다운로드 폴더   : {config.download_path}")
    print(f"보이스오버 실행 : {'예' if is_voiceover_running() else '아니오'}")
    print("-" * 66)

    problems: list[str] = []

    def check(name: str, ok: bool, ok_text: str, fail_text: str) -> None:
        print(f"[{'OK ' if ok else '확인'}] {name:<16} {ok_text if ok else fail_text}")
        if not ok:
            problems.append(f"{name}: {fail_text}")

    yt_dlp_version = ""
    try:
        import yt_dlp

        yt_dlp_version = yt_dlp.version.__version__
    except Exception:
        pass
    check("yt-dlp", bool(yt_dlp_version), yt_dlp_version, "없음 → pip install -U yt-dlp")

    if sys.platform == "darwin":
        for module in ("objc", "AppKit", "Foundation", "WebKit"):
            found = importlib.util.find_spec(module) is not None
            check(module, found, "설치됨", "없음 → pip install pyobjc-framework-Cocoa pyobjc-framework-WebKit")
    else:
        print("[정보] macOS가 아니므로 Cocoa UI는 사용할 수 없습니다 (터미널 모드 권장).")

    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        check(tool, bool(path), path or "", "없음 → brew install ffmpeg (MP4 병합/변환에 필요)")

    js_runtimes = [name for name in ("deno", "node", "bun", "quickjs", "qjs") if shutil.which(name)]
    check("JS 런타임", bool(js_runtimes), ", ".join(js_runtimes), "없음 → brew install deno (yt-dlp 유튜브 추출에 권장)")

    say = shutil.which("say")
    check("say 음성", bool(say) if sys.platform == "darwin" else True,
          say or "macOS 아님", "없음 → macOS 기본 제공 명령입니다")

    resources = Path(__file__).resolve().parent / "resources"
    for filename in ("player.html", "player.js", "vendor/yt-player.js", "vendor/LICENSE.yt-player"):
        exists = (resources / filename).exists()
        check(filename, exists, "있음", "없음 → 저장소를 다시 받으세요")

    print("-" * 66)
    if problems:
        print("다음 항목을 확인하세요:")
        for problem in problems:
            print("  -", problem)
        print("설치 도우미: ./scripts/setup_mac.sh")
        return 1
    print("필수 구성 요소가 모두 준비되었습니다. 'python -m ytaccess' 로 실행하세요.")
    return 0


# --------------------------------------------------------------------------- 자체 점검
def run_self_test() -> int:
    from .controller import AppController, InlineExecutor
    from .ui.base import NullView

    config = Config()
    config.speech_mode = "off"
    config.page_size = 50
    config.validate()
    config.save = lambda path=None: path  # type: ignore[method-assign]  # 설정 파일을 건드리지 않음

    backend = DemoBackend(total=137)
    view = NullView()
    announcer = Announcer(config, voiceover_detector=lambda: False)
    controller = AppController(config, backend, view, announcer, executor=InlineExecutor())

    steps: list[tuple[str, bool]] = []

    def expect(name: str, condition: bool) -> None:
        steps.append((name, bool(condition)))
        print(f"[{'PASS' if condition else 'FAIL'}] {name}")

    controller.start()
    expect("시작 화면에 동영상 50개", len(view.rows) == 50)
    expect("표에 제목이 표시됨", bool(view.title) and "최신순" in view.title)

    controller.load_more()
    expect("확장 후 동영상 100개", len(view.rows) == 100)

    view.selection = 96
    controller.row_selected(96)
    expect("끝 근처에서 자동 확장", len(view.rows) == 137)
    expect("마지막 페이지에서 종료 표시", controller.exhausted)

    controller.search("보이스오버")
    expect("검색 후 목록이 초기화됨", len(view.rows) == 50 and "보이스오버" in view.rows[0].title)

    view.selection = 3
    controller.copy_link(3)
    expect("링크 복사", view.clipboard.startswith("https://www.youtube.com/watch?v="))

    view.state = view.state.__class__(current_time=125.0, duration=500.0, volume=60.0)
    controller.handle_player_key("digit:3")
    controller.handle_player_key("digit:0")
    controller.handle_player_key("left")
    controller.handle_player_key("right")
    controller.handle_player_key("up")
    controller.handle_player_key("down")
    controller.handle_player_key("time")
    kinds = [call[0] for call in view.player_calls]
    expect("숫자 키 → 퍼센트 이동", "seek_percent" in kinds)
    expect("좌우 화살표 → 5초 이동", kinds.count("seek_relative") == 2)
    expect("위아래 화살표 → 볼륨 조절", kinds.count("change_volume") == 2)
    expect("L 키 → 현재 위치 음성 안내", any("현재 2분 5초" in a for a in view.announcements))

    controller.play(2)
    expect("재생 창 열기", len(view.player_opened) == 1)

    controller.handle_player_key("escape")
    expect("Esc → 재생 종료 후 표로 복귀", view.player_closed == 1 and view.table_focused >= 1)

    view.download_folder = "/tmp/ytaccess-self-test"
    controller.download(1)
    expect("MP4 다운로드가 폴더에 저장됨", len(backend.downloaded) == 1)
    expect("다운로드 완료 안내", any("다운로드 완료" in a for a in view.announcements))

    controller.close()
    failed = [name for name, ok in steps if not ok]
    print("-" * 66)
    if failed:
        print(f"{len(failed)}개 실패: " + ", ".join(failed))
        return 1
    print(f"전체 {len(steps)}개 점검 통과.")
    return 0


# --------------------------------------------------------------------------- main
def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = Config.load(args.config)
    apply_overrides(config, args)
    if args.save_config:
        path = config.save()
        print(f"설정을 저장했습니다: {path}")

    if args.doctor:
        return run_doctor(config)
    if args.self_test:
        return run_self_test()

    try:
        backend = make_backend(config, args.demo)
    except Exception as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        print("'python -m ytaccess --doctor' 로 설치 상태를 확인하세요.", file=sys.stderr)
        return 1
    announcer = make_announcer(config)

    if args.terminal or sys.platform != "darwin":
        from .ui.terminal import run_terminal

        if sys.platform != "darwin":
            print("[안내] macOS가 아니므로 Cocoa 창 대신 터미널 모드로 실행합니다.")
        return run_terminal(config, backend, announcer, demo=args.demo)

    try:
        import AppKit  # noqa: F401
        import WebKit  # noqa: F401
        import objc  # noqa: F401
    except ImportError as exc:
        print(f"[오류] macOS 네이티브 UI를 불러올 수 없습니다: {exc}", file=sys.stderr)
        print("pip install pyobjc-framework-Cocoa pyobjc-framework-WebKit", file=sys.stderr)
        print("또는 'python -m ytaccess --terminal' 로 터미널 모드를 사용하세요.", file=sys.stderr)
        return 1

    from .ui.cocoa import run_cocoa

    return run_cocoa(config, backend, announcer, demo=args.demo)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
