#!/usr/bin/env bash
# ytaccess 실행 스크립트 (프로젝트 루트에서 실행)
#
# 사용법:
#   bash run_ytaccess.sh              # 프로그램 실행
#   bash run_ytaccess.sh --doctor     # 설치 상태 점검
#   bash run_ytaccess.sh --demo       # 인터넷 없이 화면 시험
#
# 가상환경(.venv)이 없으면 scripts/setup_mac.sh를 먼저 실행합니다.
# 가상환경은 있지만 ytaccess 패키지가 설치되지 않은 경우에는 패키지만 설치합니다.
set -euo pipefail

# 스크립트가 어느 위치에서 실행되든 프로젝트 루트로 이동
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "가상환경(.venv)이 없어 설치를 먼저 진행합니다..."
  bash scripts/setup_mac.sh
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# ytaccess 패키지가 import되지 않으면 프로젝트를 편집 모드로 설치
if ! python -c "import ytaccess" >/dev/null 2>&1; then
  echo "ytaccess 패키지를 가상환경에 설치합니다..."
  python -m pip install -e .
fi

exec python -m ytaccess "$@"
