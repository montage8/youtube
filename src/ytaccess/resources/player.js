/* ytaccess 플레이어 브리지
 *
 * 두 재생 엔진을 같은 API 로 감싸서 Python(컨트롤러)이 WKWebView 에
 * JavaScript 명령만 보내도록 합니다.
 *
 *   ytplayer : yt-player 3.6.1 (YouTube IFrame Player API 래퍼)
 *   native   : yt-dlp가 찾아낸 직접 스트림 URL을 HTML5 <video>로 재생 (광고 없음)
 *
 * Python -> JS : webView.evaluateJavaScript("window.YTACCESS.xxx(...)")
 * JS -> Python : window.webkit.messageHandlers.ytaccess.postMessage(JSON문자열)
 *
 * 이 파일에는 광고 차단 코드가 없습니다. 광고 없는 재생이 필요하면
 * 설정의 player_engine 을 'adfree' 로 바꾸세요.
 */
(function () {
  'use strict';

  var native = document.getElementById('native');
  var statusEl = document.getElementById('status');
  var hintEl = document.getElementById('hint');
  var playerHost = document.getElementById('player-wrap');

  var engine = 'none';       // 'ytplayer' | 'native'
  var yt = null;             // yt-player 인스턴스
  var title = '';
  var volume = 100;
  var muted = false;
  var rate = 1;              // 재생 속도 (0.25 ~ 2배)
  var playback = 'idle';
  var lastError = '';
  var autoplayTimer = null;

  function post(type, payload) {
    try {
      var handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.ytaccess;
      if (handler) handler.postMessage(JSON.stringify(Object.assign({ type: type }, payload || {})));
    } catch (e) { /* 브라우저에서 직접 열었을 때는 조용히 무시 */ }
  }

  function clock(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h) return h + ':' + ('0' + m).slice(-2) + ':' + ('0' + sec).slice(-2);
    return m + ':' + ('0' + sec).slice(-2);
  }

  function spoken(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    var parts = [];
    if (h) parts.push(h + '시간');
    if (m) parts.push(m + '분');
    if (sec || !parts.length) parts.push(sec + '초');
    return parts.join(' ');
  }

  function currentTime() {
    if (engine === 'ytplayer') return yt ? (yt.getCurrentTime() || 0) : 0;
    if (engine === 'native') return native.currentTime || 0;
    return 0;
  }

  function duration() {
    var d = 0;
    if (engine === 'ytplayer') d = yt ? (yt.getDuration() || 0) : 0;
    else if (engine === 'native') d = native.duration;
    return (isFinite(d) && d > 0) ? d : 0;
  }

  function snapshot() {
    var d = duration(), t = currentTime();
    var message = title || '재생 중';
    if (d > 0) {
      message += ' · 현재 ' + spoken(t) + ' / 전체 ' + spoken(d) + ' (' + Math.round(t / d * 100) + '%)';
    } else {
      message += ' · 현재 ' + spoken(t);
    }
    message += ' · 볼륨 ' + Math.round(volume) + '%' + (muted ? ' (음소거)' : '');
    if (playback === 'buffering') message += ' · 버퍼링';
    if (lastError) message += ' · 오류: ' + lastError;
    return {
      engine: engine,
      playback: playback,
      currentTime: t,
      duration: d,
      volume: volume,
      muted: muted,
      title: title,
      error: lastError,
      message: message,
      clock: d > 0 ? (clock(t) + ' / ' + clock(d)) : clock(t)
    };
  }

  function emitState() {
    var s = snapshot();
    statusEl.textContent = s.message;
    post('state', { state: s });
  }

  function setState(value) {
    playback = value;
    emitState();
  }

  function armAutoplayCheck() {
    if (autoplayTimer) clearTimeout(autoplayTimer);
    autoplayTimer = setTimeout(function () {
      if (playback !== 'playing' && playback !== 'ended') {
        post('event', { name: 'autoplay_blocked' });
      }
    }, 4500);
  }

  function show(which) {
    if (which === 'ytplayer') {
      playerHost.style.display = 'block';
      native.style.display = 'none';
    } else {
      playerHost.style.display = 'none';
      native.style.display = 'block';
    }
  }

  // ---------------------------------------------------------------- yt-player
  function startYTPlayer(videoId, videoTitle) {
    stop();
    engine = 'ytplayer';
    title = videoTitle || '';
    lastError = '';
    rate = 1;
    show('ytplayer');
    // yt-player가 이전 재생에서 #player를 iframe으로 교체했으므로 다시 만듭니다.
    playerHost.innerHTML = '<div id="player"></div>';
    setState('loading');

    if (typeof window.YTPlayer !== 'function') {
      lastError = 'yt-player 번들을 불러오지 못했습니다';
      setState('error');
      post('event', { name: 'error', detail: lastError });
      return;
    }

    yt = new window.YTPlayer('#player', {
      width: '100%',
      height: '100%',
      autoplay: true,
      controls: false,       // 컨트롤은 전부 네이티브 키보드로 처리
      keyboard: false,
      fullscreen: false,
      annotations: false,
      modestBranding: true,
      related: false,
      playsInline: true,
      timeupdateFrequency: 500
    });

    yt.on('playing', function () { applyRate(); setState('playing'); post('event', { name: 'playing' }); });
    yt.on('paused', function () { setState('paused'); });
    yt.on('buffering', function () { setState('buffering'); });
    yt.on('ended', function () { setState('ended'); post('event', { name: 'ended' }); });
    yt.on('timeupdate', emitState);
    yt.on('unplayable', function () { post('event', { name: 'unplayable' }); });
    yt.on('error', function (err) {
      lastError = String(err && err.message || err || '알 수 없는 오류');
      setState('error');
      post('event', { name: 'error', detail: lastError });
    });

    yt.setVolume(volume);
    if (muted) yt.mute(); else yt.unMute();
    yt.load(videoId, true, 0);
    // 일부 macOS 환경에서는 첫 재생에 사용자 동작이 필요합니다.
    setTimeout(function () { if (yt && playback !== 'playing') yt.play(); }, 1500);
    armAutoplayCheck();
  }

  // ---------------------------------------------------------------- 직접 재생
  function startNative(url, videoTitle) {
    stop();
    engine = 'native';
    title = videoTitle || '';
    lastError = '';
    rate = 1;
    show('native');
    setState('loading');

    native.src = url;
    native.volume = volume / 100;
    native.muted = muted;
    native.autoplay = true;
    native.playsInline = true;

    native.onplaying = function () { native.playbackRate = rate; setState('playing'); post('event', { name: 'playing' }); };
    native.onpause = function () { if (playback !== 'ended') setState('paused'); };
    native.onwaiting = function () { setState('buffering'); };
    native.onended = function () { setState('ended'); post('event', { name: 'ended' }); };
    native.ontimeupdate = emitState;
    native.onerror = function () {
      lastError = '직접 스트림을 재생할 수 없습니다 (만료되었거나 차단된 주소)';
      setState('error');
      post('event', { name: 'error', detail: lastError });
    };

    var promise = native.play();
    if (promise && promise.catch) {
      promise.catch(function () { post('event', { name: 'autoplay_blocked' }); });
    }
    armAutoplayCheck();
  }

  // ---------------------------------------------------------------- 공통 조작
  function seek(seconds) {
    if (engine === 'none') return;
    var d = duration();
    var target = Math.max(0, Number(seconds) || 0);
    if (d > 0) target = Math.min(d - 0.25, target);
    if (engine === 'ytplayer') { if (yt) yt.seek(target); }
    else { try { native.currentTime = target; } catch (e) { /* 무시 */ } }
    emitState();
  }

  function seekPercent(percent) {
    var d = duration();
    if (d > 0) seek(d * (Math.max(0, Math.min(100, Number(percent) || 0)) / 100));
    else emitState();
  }

  function seekRelative(delta) { seek(currentTime() + (Number(delta) || 0)); }

  function setVolume(value) {
    volume = Math.max(0, Math.min(100, Number(value) || 0));
    if (engine === 'ytplayer' && yt) yt.setVolume(volume);
    if (engine === 'native') native.volume = volume / 100;
    emitState();
  }

  function changeVolume(delta) { setVolume(volume + (Number(delta) || 0)); }

  // 재생 속도 (0.25 ~ 2배). 0배는 재생이 멈추므로 허용하지 않습니다.
  function applyRate() {
    if (engine === 'ytplayer' && yt) yt.setPlaybackRate(rate);
    else if (engine === 'native') native.playbackRate = rate;
  }

  function setRate(value) {
    var r = Number(value);
    if (!isFinite(r) || r <= 0) r = 1;
    rate = Math.max(0.25, Math.min(2, r));
    applyRate();
    emitState();
  }

  function muteToggle() {
    muted = !muted;
    if (engine === 'ytplayer' && yt) { if (muted) yt.mute(); else yt.unMute(); }
    if (engine === 'native') native.muted = muted;
    emitState();
  }

  function play() {
    if (engine === 'ytplayer' && yt) yt.play();
    else if (engine === 'native') { var p = native.play(); if (p && p.catch) p.catch(function () {}); }
  }

  // 연속 반복: 처음으로 되돌린 뒤 다시 재생합니다.
  function restart() {
    seek(0);
    play();
  }

  function pause() {
    if (engine === 'ytplayer' && yt) yt.pause();
    else if (engine === 'native') native.pause();
  }

  function toggle() {
    if (playback === 'playing' || playback === 'buffering' || playback === 'loading') pause();
    else play();
  }

  function stop() {
    if (autoplayTimer) { clearTimeout(autoplayTimer); autoplayTimer = null; }
    if (yt) { try { yt.stop(); yt.destroy(); } catch (e) { /* 무시 */ } }
    yt = null;
    try {
      native.pause();
      native.removeAttribute('src');
      native.load();
    } catch (e) { /* 무시 */ }
    playerHost.innerHTML = '';   // yt-player가 만든 iframe 제거
    lastError = '';
    playback = 'idle';
    engine = 'none';
  }

  window.YTACCESS = {
    ready: function () { return true; },
    startYTPlayer: startYTPlayer,
    startNative: startNative,
    seek: seek,
    seekPercent: seekPercent,
    seekRelative: seekRelative,
    setVolume: setVolume,
    changeVolume: changeVolume,
    setRate: setRate,
    muteToggle: muteToggle,
    play: play,
    pause: pause,
    toggle: toggle,
    restart: restart,
    stop: stop,
    state: function () { return JSON.stringify(snapshot()); },
    version: '1.0'
  };

  // 메시지 핸들러가 아직 등록되지 않았을 때를 대비한 주기적 상태 전송
  setInterval(emitState, 1000);
  hintEl.textContent = "숫자 0~9 위치 이동 · ; ' 5초 뒤·앞 · U D 볼륨 · F S 속도 · L 현재 위치 · Esc 닫기";
  post('event', { name: 'ready' });
  emitState();
})();
