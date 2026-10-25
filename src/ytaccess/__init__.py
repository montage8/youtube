"""ytaccess - 보이스오버 사용자를 위한 macOS 유튜브 프로그램.

구성:
    backend     yt-dlp 기반 검색/다운로드/스트림 URL 추출
    controller  UI와 무관한 앱 동작(검색, 무한 확장, 재생 키, 다운로드)
    ui          Cocoa(보이스오버 네이티브) / 터미널(진단·백업) 화면
    resources   yt-player 번들 + 플레이어 HTML/JS
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
