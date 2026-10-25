"""음성 안내.

보이스오버가 실행 중이면 NSAccessibility 공지(announcement)로 읽어주고,
그렇지 않으면 macOS의 ``say`` 명령으로 읽어줍니다.
Cocoa 쪽 코드는 ``voiceover_hook`` 으로 주입하므로 이 모듈은 맥이 아닌
환경에서도 그대로 테스트할 수 있습니다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from typing import Callable

from .config import Config


def is_voiceover_running() -> bool:
    """VoiceOver 프로세스가 떠 있는지 확인 (실패하면 False)."""
    if sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["pgrep", "-x", "VoiceOver"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class KoreanVoice:
    """``say -v ?`` 목록에서 한국어 목소리를 찾습니다."""

    def __init__(self) -> None:
        self._voices: list[str] | None = None

    def available(self) -> list[str]:
        if self._voices is None:
            self._voices = []
            if sys.platform == "darwin" and shutil.which("say"):
                try:
                    output = subprocess.run(
                        ["say", "-v", "?"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    ).stdout
                    for line in output.splitlines():
                        if "ko_KR" in line:
                            self._voices.append(line.split()[0])
                except (OSError, subprocess.SubprocessError):
                    pass
        return list(self._voices)

    def best(self) -> str:
        voices = self.available()
        return voices[0] if voices else ""


class Announcer:
    """앱의 모든 안내 메시지를 한 곳에서 처리합니다."""

    def __init__(
        self,
        config: Config,
        voiceover_hook: Callable[[str, str], None] | None = None,
        voiceover_detector: Callable[[], bool] | None = None,
        runner: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.config = config
        self.voiceover_hook = voiceover_hook
        self.voiceover_detector = voiceover_detector or is_voiceover_running
        self.runner = runner
        self.korean_voice = KoreanVoice()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self.spoken: list[str] = []  # 테스트/디버깅용 기록

    def speak(self, text: str, priority: str = "normal") -> None:
        text = (text or "").strip()
        if not text or self.config.speech_mode == "off":
            return
        with self._lock:
            self.spoken.append(text)
        mode = self.config.speech_mode
        announced = False

        want_announcement = mode in ("voiceover", "both") or (
            mode == "auto" and self.voiceover_detector()
        )
        if want_announcement and self.voiceover_hook:
            try:
                self.voiceover_hook(text, priority)
                announced = True
            except Exception:
                announced = False

        want_say = mode in ("say", "both") or (mode == "auto" and not announced)
        if want_say:
            self._say(text)

    def _say(self, text: str) -> None:
        if sys.platform != "darwin" or not shutil.which("say"):
            return  # 다른 플랫폼에서는 조용히 무시 (터미널 UI가 대신 출력)
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except OSError:
                    pass
            voice = self.config.speech_voice.strip() or self.korean_voice.best()
            command = ["say"]
            if voice:
                command += ["-v", voice]
            command += ["-r", str(self.config.speech_rate), text]
            try:
                if self.runner:
                    self.runner(command)
                else:
                    self._process = subprocess.Popen(
                        command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            except OSError:
                self._process = None

    def stop(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except OSError:
                    pass
            self._process = None
