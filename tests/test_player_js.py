"""재생 창 player.js 동작 검사 (Node.js가 있을 때만 실행)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parent / "player_js_check.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js가 없어 건너뜁니다")
def test_player_js_playback_rate() -> None:
    result = subprocess.run(
        ["node", str(CHECK)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NO_ERROR" in result.stdout
