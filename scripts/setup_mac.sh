#!/usr/bin/env bash
# ytaccess 맥 설치 도우미
#
# 실행 방법 (터미널에서):
#   curl -fsSL https://raw.githubusercontent.com/montage8/youtube/arena/f8c0623d-youtube/scripts/setup_mac.sh | bash
# 또는 저장소를 클론한 뒤:
#   bash scripts/setup_mac.sh
set -euo pipefail

echo "=== ytaccess 맥 설치 도우미 ==="
echo

# 1. Homebrew 확인/설치
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew가 없습니다. 설치합니다..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null || true)"

# 2. 필수 도구 설치: ffmpeg (MP4 병합), deno (yt-dlp 유튜브 추출 권장)
echo "ffmpeg, deno 설치를 확인합니다..."
brew install ffmpeg deno >/dev/null 2>&1 || brew upgrade ffmpeg deno >/dev/null 2>&1 || true

# 3. Python 가상환경 (권장)
if [ ! -d .venv ]; then
  echo "Python 가상환경을 만듭니다..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 4. Python 의존성 설치
echo "Python 라이브러리를 설치합니다..."
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r requirements.txt

# 5. 설정 파일 초기 생성
python - <<'PY'
from pathlib import Path
from ytaccess.config import default_config_path, Config
path = default_config_path()
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    Config().save(path)
    print(f"설정 파일 생성: {path}")
else:
    print(f"설정 파일 이미 있음: {path}")
PY

echo
echo "=== 설치 완료 ==="
echo "실행: source .venv/bin/activate && python -m ytaccess"
echo "진단: source .venv/bin/activate && python -m ytaccess --doctor"
echo "오프라인 UI 시험: source .venv/bin/activate && python -m ytaccess --demo"
