# 벤더링된 yt-player

* 원본: [feross/yt-player](https://github.com/feross/yt-player) v3.6.1 (MIT)
* 출처: `https://registry.npmjs.org/yt-player/-/yt-player-3.6.1.tgz`
* 라이선스 원문: [LICENSE.yt-player](LICENSE.yt-player)
* 변환: 원본 `index.js` + 의존성 `load-script2`, `events` 브라우저 심을
  Browserify로 묶어 `window.YTPlayer` 전역으로 노출했습니다. 소스 코드는 변경하지
  않았습니다.

다시 만들려면 (Node.js 필요):

```bash
./scripts/bundle_yt_player.sh
```

WKWebView의 `player.html`에서 `<script src="vendor/yt-player.js"></script>`로
불러옵니다. `player.js`가 `new window.YTPlayer('#player', {...})` 로 플레이어를
만들고 `load / seek / setVolume / getDuration / getCurrentTime` 등을 호출합니다.
