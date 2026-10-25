# ytaccess — 보이스오버 사용자를 위한 macOS 유튜브 프로그램

mac에서 보이스오버(VoiceOver)로 편하게 쓸 수 있는, **광고 없는 유튜브 탐색·재생·다운로드 프로그램**입니다. 오픈소스 `yt-dlp`(검색·다운로드)와 `yt-player`(유튜브 iframe 플레이어)를 파이썬(AppKit/Cocoa)로 감쌌습니다.

처음 켰을 때 최신순 동영상 표가 보이고, 표에서 위아래 화살표로 이동한 뒤 엔터나 이중 클릭으로 재생합니다. 보이스오버가 제목·채널·길이·날짜·조회수를 한 줄로 읽어줍니다.

> 🎧 **대상 사용자:** 시각장애인 (보이스오버 완전 지원)  
> 🖥️ **플랫폼:** macOS (AppKit + WKWebView). 그 외 플랫폼/진단은 터미널 모드 지원.

---

## 1. 설치 (맥 전용)

### 사전 준비
* macOS
* Homebrew (`/bin/bash -c "$(curl -fsSL ...)"`)
* Python 3.10+

### 설치 스크립트 (권장)

```bash
git clone https://github.com/montage8/youtube.git
cd youtube
bash scripts/setup_mac.sh
```

스크립트가 하는 일:
1. Homebrew로 `ffmpeg`(MP4 병합), `deno`(yt-dlp 유튜브 추출 권장) 설치
2. Python 가상환경(`.venv`) 생성 및 `requirements.txt` 설치 (`yt-dlp`, `pyobjc-framework-Cocoa`, `pyobjc-framework-WebKit`)
3. 설정 파일 `~/Library/Application Support/ytaccess/settings.json` 생성

### 수동 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 설치 확인

```bash
source .venv/bin/activate
python -m ytaccess --doctor
```

필수 항목(yt-dlp, PyObjC, ffmpeg, JS 런타임, 플레이어 번들)이 모두 OK 여야 합니다.

---

## 2. 실행

```bash
source .venv/bin/activate
python -m ytaccess
```

처음 켜면 **최신순 동영상 50개**가 표에 펼쳐집니다. 표 끝에 가까워지면 50개씩 자동으로 추가됩니다(없을 때까지).

다른 옵션:

| 명령 | 설명 |
|------|------|
| `python -m ytaccess --demo` | 인터넷 없이 가짜 데이터로 UI 동작 시험 |
| `python -m ytaccess --terminal` | 터미널 모드 (macOS가 아니거나 진단용) |
| `python -m ytaccess --engine adfree` | 광고 없는 직접 스트림 재생 엔진 시작 |
| `python -m ytaccess --self-test` | 핵심 로직 자체 점검 |

---

## 3. 화면 구성

앱을 켜면 세 부분이 보입니다.

1. **검색창 (상단):** 검색어를 입력하고 엔터를 누르면 검색 결과가 표에 표시됩니다.
2. **동영상 표 (가운데):** 최신순(또는 관련도순) 동영상 목록. 보이스오버가 각 행을 한 줄로 읽어줍니다.
3. **상태줄 (하단):** 현재 상황과 안내 메시지.

표의 한 행 예시(보이스오버 읽기):

> "1번, 전체 50개 중, 오늘의 주요 뉴스 정리, 채널 오늘의 뉴스, 길이 10분 23초, 2026년 10월 20일 업로드, 조회수 1.2만회. 엔터 키 또는 이중 클릭으로 재생합니다."

표 끝(마지막 5개)에 커서가 닿으면 50개를 자동으로 더 불러옵니다(명령+E로도 수동 확장).

---

## 4. 키보드 단축키

모든 조작은 키보드만으로 가능합니다. 재생 창에서도 동일하게 작동합니다.

### 동영상 표

| 키 | 동작 |
|----|------|
| 위 / 아래 화살표 | 이전 / 다음 동영상 (보이스오버가 행 전체를 읽어줌) |
| 엔터 또는 이중 클릭 | 선택 동영상 재생 |
| Command + F | 검색창으로 이동 (검색어 입력 후 엔터) |
| Command + L | 선택 동영상 링크를 클립보드에 복사 |
| Command + D | 선택 동영상을 MP4로 다운로드 (저장 폴더 선택 대화상자) |
| Command + R | 현재 목록 새로고침 |
| Command + E | 동영상 50개 더 불러오기 |
| Command + 1 | 최신순 정렬 |
| Command + 2 | 관련도순 정렬 |
| Command + 0 | 홈(최신순 동영상)으로 돌아가기 |
| Command + , | 홈 검색어 변경 |
| Command + / | 단축키 안내 |

### 재생 중

| 키 | 동작 |
|----|------|
| 숫자 0~9 (키패드 포함) | 영상 길이의 0~90% 지점으로 이동 (0 = 처음으로) |
| 왼쪽 / 오른쪽 화살표 | 5초 뒤로 / 5초 앞으로 |
| 위 / 아래 화살표 | 볼륨 올리기 / 내리기 |
| L | 현재 재생 위치를 음성으로 읽어주기 |
| Command + T | 연속 반복 켜기 / 끄기 (켜면 영상이 끝나도 같은 영상을 다시 재생) |
| Command + N | 다음 영상 자동 재생 켜기 / 끄기 (재생목록에서 재생한 경우, 끝나면 표에서 바로 아래 영상 재생) |
| 스페이스바 | 재생 / 일시정지 |
| M | 음소거 켜기 / 끄기 |
| Esc | 재생 종료 후 동영상 표로 복귀 |

### 음성 안내

보이스오버가 켜져 있으면 보이스오버 공지로, 꺼져 있으면 macOS의 `say` 음성으로 안내합니다. 설정 파일(`speech_mode`)로 `auto | voiceover | say | both | off` 중 하나를 고를 수 있습니다.

---

## 5. 다운로드

표에서 동영상을 고른 뒤 **Command + D**를 누르면 MP4 저장 폴더를 고르는 네이티브 대화상자가 뜹니다. 폴더를 선택하면 즉시 다운로드가 시작되고, 완료 시 음성으로 알려줍니다. yt-dlp가 `bv*[ext=mp4]+ba[ext=m4a]` 형태의 MP4 스트림을 받아 ffmpeg로 병합합니다.

> 연령 제한 영상은 `코드 > cookies-from-browser` 설정에 `safari`나 `chrome`을 입력해 쿠키를 가져오게 할 수 있습니다.

---

## 6. 설정

`~/Library/Application Support/ytaccess/settings.json`

주요 항목:

| 항목 | 의미 | 기본값 |
|------|------|--------|
| `page_size` | 한 번에 더 불러올 동영상 수 | 50 |
| `preload_threshold` | 표 끝에서 몇 개 남으면 자동 확장할지 | 5 |
| `search_sort` | 검색 결과 정렬 (`relevance` / `latest`) | `relevance` |
| `home_mode` | 홈 피드 종류 (`latest` / `trending`) | `latest` |
| `home_query` | 홈 최신순 기본 검색어 | `뉴스` |
| `player_engine` | 재생 엔진 (`ytplayer` / `adfree`) | `ytplayer` |
| `speech_mode` | 음성 안내 방식 (`auto` / `voiceover` / `say` / `both` / `off`) | `auto` |
| `download_dir` | MP4 기본 저장 폴더 | `~/Downloads` |
| `download_subtitles` | 자막도 함께 저장 | `false` |
| `cookies_from_browser` | 쿠키 가져올 브라우저 (`safari`, `chrome` …) | `` |

명령행으로도 덮어쓸 수 있습니다:

```bash
python -m ytaccess --engine adfree --page-size 100 --speech voiceover
```

---

## 7. 접근성 설계 (보이스오버)

* **네이티브 AppKit 컨트롤만 사용:** NSTableView, NSSearchField, NSButton, NSMenu 등은 macOS 접근성(AX) 트리를 그대로 제공합니다.
* **표 행 완전 라벨:** 각 행에 보이스오버가 한 번에 읽을 수 있는 완전한 문장을 붙입니다(번호, 전체 개수, 제목, 채널, 길이, 날짜, 조회수, 재생 안내).
* **메뉴로 모든 명령:** 보이스오버 사용자는 VO + M으로 메뉴를 탐색해 재생·검색·다운로드·정렬을 할 수 있습니다.
* **재창은 단일 AX 요소:** 재생 창은 유튜브 iframe 내부 복잡한 웹 AX 트리를 보이스오버가 헤매지 않게, 접근성 요소 하나로 취급합니다.
* **상태 공지:** 검색 완료, 자동 확장, 다운로드 진행, 오류 등을 음성 공지로 알립니다.

---

## 8. 프로젝트 구조

```
src/ytaccess/
  __init__.py      패키지 버전
  cli.py           명령행 진입점 (--doctor, --self-test, --demo …)
  config.py        사용자 설정 (설정 파일 읽기/쓰기)
  models.py        Video, Page, PlayerState 데이터 구조
  formatting.py    보이스오버용 한국어 문자열 생성
  backend.py       yt-dlp 기반 검색 / MP4 다운로드 / 스트림 URL 추출
  speech.py        보이스오버 / say 음성 안내
  demo_backend.py  오프라인 UI 시험용 가짜 백엔드
  controller.py    UI 무관 앱 로직 (검색, 확장, 재생 키, 다운로드)
  ui/
    base.py        화면 인터페이스 / 키 동작 매핑
    terminal.py    터미널 화면 (진단·백업)
    cocoa.py       macOS Cocoa 화면 (보이스오버 주 화면)
    cocoa_player.py WKWebView + yt-player 재생 창
    cocoa_bridge.py 음성 공지, 클립보드, 폴더 선택 등 macOS 도우미
  resources/
    player.html    재생 페이지
    player.js      yt-player 브리지 (ytplayer / native 엔진)
    vendor/
      yt-player.js  yt-player 3.6.1 브라우저 번들 (MIT, feross/yt-player)
      LICENSE.yt-player
tests/             (추가 예정)
scripts/
  setup_mac.sh     맥 설치 도우미
```

---

## 9. 기여 및 라이선스

이 프로그램은 MIT 라이선스 오픈소스입니다. 시각장애인 접근성을 개선하는 pull request를 환영합니다.

* 포함 오픈소스: `yt-dlp` (Unlicense), `yt-player` 3.6.1 (MIT, Feross Aboukhadijeh), `PyObjC` (MIT).
* 저장소: https://github.com/montage8/youtube

문제나 기능 제안은 GitHub Issues에 남겨 주세요.
