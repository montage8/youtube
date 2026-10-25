// 재생 창 player.js의 재생 속도 동작을 가짜 YouTube 플레이어로 검사합니다.
// 실행: node tests/player_js_check.js (pytest의 test_player_js.py가 자동으로 호출)
const fs = require('fs');
// 실행 위치와 무관하게 저장소의 player.js를 읽습니다.
const path = require('path');
const src = fs.readFileSync(process.env.PLAYER_JS || path.join(__dirname, '..', 'src', 'ytaccess', 'resources', 'player.js'), 'utf8');

function el(id) {
  const e = {
    id, style: {}, textContent: '', innerHTML: '', src: '', volume: 1, muted: false,
    currentTime: 0, duration: 0, playbackRate: 1, autoplay: false, playsInline: false,
    classList: { add() {}, remove() {}, toggle() {} },
    addEventListener() {}, removeAttribute() {}, load() {}, pause() {},
    play() { return Promise.resolve(); }, appendChild() {}, setAttribute() {},
  };
  return e;
}
const elements = {};
global.document = { getElementById(id) { return elements[id] || (elements[id] = el(id)); }, createElement: () => el('x') };
global.window = {};
global.webkit = undefined;

// 가짜 YouTube 플레이어 (yt-player 래퍼 흉내)
const calls = [];
const listeners = {};
window.YTPlayer = function (sel, opts) {
  this.on = (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); };
  const rec = (name) => (...a) => calls.push([name, ...a]);
  for (const n of ['setVolume','mute','unMute','load','play','pause','seek','stop','destroy','setPlaybackRate']) this[n] = rec(n);
  this.getCurrentTime = () => 0;
  this.getDuration = () => 100;
};
function fire(ev) { (listeners[ev] || []).forEach(f => f()); }

const states = [];
// player.js 실행
new Function(src)();
const Y = window.YTACCESS;
const check = (name, cond) => { console.log((cond ? 'PASS ' : 'FAIL ') + name); if (!cond) process.exitCode = 1; };

let threw = null;
try { Y.startYTPlayer('abc', '테스트 영상'); } catch (e) { threw = e; }
check('startYTPlayer 오류 없음', !threw);

calls.length = 0;
try { Y.setRate(1.25); } catch (e) { threw = e; }
check('setRate(1.25) 오류 없음', !threw);
check('setRate → yt.setPlaybackRate(1.25) 호출', calls.some(c => c[0] === 'setPlaybackRate' && c[1] === 1.25));

calls.length = 0;
fire('playing');
check('재생 시작 시 속도 다시 적용', calls.some(c => c[0] === 'setPlaybackRate' && c[1] === 1.25));

calls.length = 0;
Y.setRate(0);
check('0배 입력 → 1배로 보정', calls.some(c => c[0] === 'setPlaybackRate' && c[1] === 1));
Y.setRate(9);
check('2배 초과 → 2배로 제한', calls.some(c => c[0] === 'setPlaybackRate' && c[1] === 2));

calls.length = 0;
Y.startYTPlayer('def', '다음 영상');
check('새 영상 시작 시 속도 1배로 초기화 (재생 시작 후)', (fire('playing'), calls.some(c => c[0] === 'setPlaybackRate' && c[1] === 1)));

console.log(threw ? "ERROR: " + threw : "NO_ERROR");
process.exit(process.exitCode || 0);
