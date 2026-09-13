#!/usr/bin/env python3
"""
ttyd-web-control proxy: keep stock ttyd UI, inject a mobile-friendly
control bar (Korean input, shortcut keys, page scroll, font size),
file upload, and helper endpoints.

- ttyd: 127.0.0.1:7682 (internal only)
- proxy: 0.0.0.0:7681 (public)

All paths/ports/sessions are overridable via environment variables
so any machine can run this without editing code (see README).
"""

import asyncio
import aiohttp
from aiohttp import web
import re
import os
import shutil
import datetime
from collections import deque

TTYD_HOST = os.environ.get("TTYD_HOST", "127.0.0.1")
TTYD_PORT = int(os.environ.get("TTYD_PORT", "7682"))
PROXY_PORT = int(os.environ.get("PROXY_PORT", "7681"))
TMUX_SESSION = os.environ.get("TMUX_SESSION", "agy")
UPLOAD_DIR = os.path.expanduser(os.environ.get("TTYD_UPLOAD_DIR", "~/ttyd-uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# tmux binary auto-detection (falls back to the macOS Homebrew path)
TMUX_BIN = shutil.which("tmux") or "/usr/local/bin/tmux"

# 현재 활성 ttyd WebSocket 연결 저장소
active_ttyd_ws = None

# 터미널 최근 출력 기록 버퍼 (최대 1000 청크 / 약 5000줄)
terminal_buffer = deque(maxlen=2000)

# ANSI 이스케이프 코드 제거 정규식
ANSI_REGEX = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b\([a-zA-Z]|\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\r')

def clean_ansi(text: str) -> str:
    cleaned = ANSI_REGEX.sub('', text)
    # 캐리지 리턴 및 공백 정리
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return '\n'.join(lines)

HEAD_INJECT = """
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=auto">
<meta name="apple-mobile-web-app-capable" content="no">
<meta name="apple-mobile-web-app-title" content="Terminal">
<meta name="theme-color" content="#101216">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="apple-touch-icon-precomposed" href="/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon.png">
<link rel="manifest" href="/manifest.json">
<style>
  html, body {
    width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important;
    background: #212121 !important;
    display: flex !important;
    flex-direction: column !important;
    padding-left: env(safe-area-inset-left, 0px) !important;
    padding-right: env(safe-area-inset-right, 0px) !important;
  }
  #terminal-container {
    flex: 1 1 auto !important;
    min-height: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    padding: 0 !important;
    margin: 0 !important;
    box-sizing: border-box !important;
    overflow: hidden !important;
  }
  .xterm, .xterm-screen { width: 100% !important; }
  .xterm-viewport {
    width: 100% !important;
    overflow-y: hidden !important; /* iOS Safari가 내부 viewport 스크롤 끝에 도달했을 때 제스처를 락킹하는 현상 방지 */
  }
  /* DOM 렌더러 기반 텍스트 완벽 선택 허용 */
  .xterm, .xterm-screen, .xterm-viewport, .xterm-rows, .xterm-rows > div, .xterm-rows span {
    user-select: text !important;
    -webkit-user-select: text !important;
    -webkit-touch-callout: default !important;
  }
  input, textarea, select { font-size: 16px !important; touch-action: manipulation; }
</style>
"""

BODY_INJECT = """
<style>
  #agl-bar {
    flex: 0 0 auto;
    background: #161616;
    border-top: 1px solid #282828;
    padding-bottom: env(safe-area-inset-bottom, 0px);
    width: 100%;
  }
  #agl-handle-bar {
    width: 100%;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    user-select: none;
    -webkit-user-select: none;
    touch-action: none;
    padding: 2px 0;
  }
  #agl-handle-pill {
    width: 36px;
    height: 4px;
    border-radius: 2px;
    background: #4e4e52;
    transition: background 0.15s ease, transform 0.15s ease;
  }
  #agl-handle-bar:active #agl-handle-pill {
    background: #888;
    transform: scaleY(1.2);
  }
  #agl-ctrl-container {
    padding: 0 10px 4px;
    user-select: none;
    -webkit-user-select: none;
    overflow: hidden;
    box-sizing: border-box;
  }
  #agl-bar[data-mode="0"] #agl-ctrl-container {
    height: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    display: none;
  }
  #agl-bar[data-mode="1"] #agl-ctrl-container {
    height: 31px;
  }
  #agl-bar[data-mode="1"] #agl-grid-2row {
    display: none !important;
  }
  #agl-bar[data-mode="1"] #agl-grid-1row {
    display: flex !important;
  }
  #agl-bar[data-mode="2"] #agl-ctrl-container {
    height: 58px;
  }
  #agl-bar[data-mode="2"] #agl-grid-1row {
    display: none !important;
  }
  #agl-bar[data-mode="2"] #agl-grid-2row {
    display: flex !important;
  }
  #agl-bar[data-mode="3"] #agl-ctrl-container {
    height: 88px; /* 페이지 27 + 간격 3 + 2줄 54 + 하단패딩 4 = 88 */
    display: flex;
    flex-direction: column;
  }
  #agl-bar[data-mode="3"] #agl-grid-1row {
    display: none !important;
  }
  #agl-bar[data-mode="3"] #agl-grid-2row {
    display: flex !important;
  }
  #agl-bar[data-mode="3"] #agl-page-row {
    display: flex !important;
    margin-bottom: 3px; /* flex gap 대신 margin (구형 Safari 호환) */
  }
  #agl-bar[data-mode="0"] #agl-page-row,
  #agl-bar[data-mode="1"] #agl-page-row,
  #agl-bar[data-mode="2"] #agl-page-row {
    display: none !important;
  }

  /* 3줄 모드: 페이지 스크롤 (1줄 패턴과 동일 고정 높이) */
  #agl-page-row {
    display: none;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
    height: 27px;
    flex-shrink: 0;
  }
  #agl-page-row .agl-k {
    flex: 1 1 0;
    height: 25px;
    font-size: 12px;
  }

  /* 2줄 모드 레이아웃 */
  #agl-grid-2row {
    justify-content: space-between;
    align-items: center;
  }
  .agl-ctrl-left {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
  }
  .agl-ctrl-right-grid {
    display: grid;
    grid-template-columns: 44px 30px 30px;
    grid-template-rows: 25px 25px;
    gap: 4px;
    align-items: center;
  }
  .agl-k-empty {
    width: 30px;
    height: 25px;
  }
  .agl-k-left-arrow {
    justify-self: end;
  }

  /* 1줄 모드 레이아웃 */
  #agl-grid-1row {
    justify-content: space-between;
    align-items: center;
    height: 27px;
  }
  .agl-ctrl-left-1row {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .agl-ctrl-right-1row {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  /* 공통 키캡 스타일 (컴팩트 25px 높이) */
  .agl-k {
    background: linear-gradient(180deg, #2c2c2e 0%, #1f1f21 100%);
    color: #f2f2f7;
    border: 1px solid #3c3c40;
    border-radius: 5px;
    padding: 0;
    height: 25px;
    font-size: 11px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 3px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08);
    transition: transform 0.05s ease, background 0.05s ease;
  }
  .agl-k:active {
    background: #3a3a3e;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    transform: translateY(1px);
    color: #fff;
  }
  .agl-k-esc { width: 38px; }
  .agl-k-tab { width: 46px; }
  .agl-k-enter-2row { width: 44px; }
  .agl-k-enter-1row { width: 46px; }
  .agl-k-arrow { width: 30px; font-size: 13px; }
  #agl-input-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px 5px;
  }
  #agl-text {
    flex: 1;
    background: #2d2d2d;
    color: #f0f0f0;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 7px 10px;
    font-size: 16px;
    font-family: 'Menlo', 'Monaco', monospace;
    outline: none;
    -webkit-appearance: none;
    caret-color: #f0f0f0;
  }
  #agl-text:focus { border-color: #888; }
  #agl-text::placeholder { color: #555; font-size: 13px; }
  #agl-send {
    flex-shrink: 0;
    background: #3c3c3c;
    color: #e0e0e0;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 7px 13px;
    font-size: 13px;
    font-family: 'Menlo', monospace;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
    white-space: nowrap;
    min-height: 36px;
  }
  #agl-attach-btn {
    flex-shrink: 0;
    background: #282828;
    color: #ccc;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 0;
    width: 34px;
    height: 36px;
    font-size: 20px;
    font-weight: 300;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  #agl-attach-btn:active { background: #505050; color: #fff; }

  #agl-preview-bar {
    display: none;
    background: #23272e;
    border-bottom: 1px solid #333;
    padding: 6px 10px;
    align-items: center;
    gap: 8px;
    animation: aglSlideUp 0.15s ease-out;
  }
  @keyframes aglSlideUp {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }
  .agl-preview-thumb {
    width: 34px;
    height: 34px;
    border-radius: 4px;
    border: 1px solid #444;
    object-fit: cover;
    background: #181818;
    flex-shrink: 0;
  }
  .agl-preview-icon {
    width: 34px;
    height: 34px;
    border-radius: 4px;
    border: 1px solid #444;
    background: #2a2a2a;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
  }
  .agl-preview-details {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 1px;
  }
  .agl-preview-name {
    color: #e0e0e0;
    font-size: 12px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .agl-preview-size {
    color: #777;
    font-size: 10px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .agl-preview-cancel {
    background: #333;
    border: 1px solid #444;
    color: #aaa;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    flex-shrink: 0;
    -webkit-tap-highlight-color: transparent;
  }
  .agl-preview-cancel:active {
    background: #e05555;
    color: #fff;
    border-color: #e05555;
  }

  #agl-send:active { background: #555; }

</style>

<div id="agl-bar" data-mode="2">
  <div id="agl-preview-bar">
    <div id="agl-preview-media"></div>
    <div class="agl-preview-details">
      <span id="agl-preview-name" class="agl-preview-name"></span>
      <span id="agl-preview-size" class="agl-preview-size"></span>
    </div>
    <button id="agl-preview-cancel" class="agl-preview-cancel" type="button" title="첨부 취소">✕</button>
  </div>
  <div id="agl-handle-bar" title="당겨서 0~3줄 조절">
    <div id="agl-handle-pill"></div>
  </div>
  <div id="agl-ctrl-container">
    <!-- 3줄 모드: 페이지 스크롤 (2줄 위로 스택) -->
    <div id="agl-page-row">
      <button class="agl-k" data-seq="PGUP">PgUp ▲</button>
      <button class="agl-k" data-seq="PGDN">PgDn ▼</button>
      <button class="agl-k agl-k-font" data-font="inc" title="글자 크게">A+</button>
      <button class="agl-k agl-k-font" data-font="dec" title="글자 작게">A−</button>
      <button class="agl-k agl-k-font" data-font="reset" title="글자 크기 초기화">리셋</button>
    </div>
    <!-- 2줄 모드 -->
    <div id="agl-grid-2row">
      <div class="agl-ctrl-left">
        <button class="agl-k agl-k-esc" data-seq="ESC">Esc</button>
        <button class="agl-k agl-k-tab" data-seq="TAB">Tab</button>
      </div>
      <div class="agl-ctrl-right-grid">
        <button class="agl-k agl-k-enter-2row" data-seq="ENTER">Enter</button>
        <button class="agl-k agl-k-arrow" data-seq="UP">↑</button>
        <div class="agl-k-empty"></div>
        <button class="agl-k agl-k-arrow agl-k-left-arrow" data-seq="LEFT">←</button>
        <button class="agl-k agl-k-arrow" data-seq="DOWN">↓</button>
        <button class="agl-k agl-k-arrow" data-seq="RIGHT">→</button>
      </div>
    </div>
    <!-- 1줄 모드 -->
    <div id="agl-grid-1row">
      <div class="agl-ctrl-left-1row">
        <button class="agl-k agl-k-esc" data-seq="ESC">Esc</button>
        <button class="agl-k agl-k-tab" data-seq="TAB">Tab</button>
      </div>
      <div class="agl-ctrl-right-1row">
        <button class="agl-k agl-k-enter-1row" data-seq="ENTER">Enter</button>
        <button class="agl-k agl-k-arrow" data-seq="LEFT">←</button>
        <button class="agl-k agl-k-arrow" data-seq="UP">↑</button>
        <button class="agl-k agl-k-arrow" data-seq="DOWN">↓</button>
        <button class="agl-k agl-k-arrow" data-seq="RIGHT">→</button>
      </div>
    </div>
  </div>
  <div id="agl-input-row">
    <input type="file" id="agl-file-input" style="display:none;" />
    <button id="agl-attach-btn" type="button" title="사진/파일 첨부">+</button>
    <input id="agl-text" type="text"
      placeholder="입력 후 전송..."
      autocomplete="off" autocorrect="off"
      autocapitalize="off" spellcheck="false"
      enterkeyhint="send" />
    <button id="agl-send" style="background:#273244;border-color:#3e4f6d;color:#e2e8f0;">전송↵</button>
  </div>
</div>

<script>
(function() {
  var bar           = document.getElementById('agl-bar');
  var handleBar     = document.getElementById('agl-handle-bar');
  var ctrlContainer = document.getElementById('agl-ctrl-container');
  var sendBtn       = document.getElementById('agl-send');
  var input         = document.getElementById('agl-text');

  var grid2Row      = document.getElementById('agl-grid-2row');
  var grid1Row      = document.getElementById('agl-grid-1row');
  var pageRow       = document.getElementById('agl-page-row');

  var MODE_HEIGHTS = [0, 31, 58, 88]; // 0줄: 0px, 1줄: 31px, 2줄: 58px, 3줄(페이지+2줄 스택): 88px
  var currentMode = 2;
  try {
    var saved = localStorage.getItem('agl_bar_mode');
    if (saved === '0' || saved === '1' || saved === '2' || saved === '3') {
      currentMode = parseInt(saved, 10);
    }
  } catch (e) {}

  function applyModeDOM(mode) {
    if (bar) bar.setAttribute('data-mode', mode);
    if (ctrlContainer) {
      ctrlContainer.style.transition = '';
      ctrlContainer.style.height = '';
      if (mode === 0) {
        ctrlContainer.style.display = 'none';
      } else {
        ctrlContainer.style.display = 'block';
        if (grid1Row) grid1Row.style.display = (mode === 1) ? 'flex' : 'none';
        if (grid2Row) grid2Row.style.display = (mode === 2 || mode === 3) ? 'flex' : 'none';
        if (pageRow) pageRow.style.display = (mode === 3) ? 'flex' : 'none';
      }
    }
  }

  function setMode(mode, save) {
    currentMode = Math.max(0, Math.min(3, mode));
    applyModeDOM(currentMode);
    if (save !== false) {
      try { localStorage.setItem('agl_bar_mode', currentMode); } catch (e) {}
    }
    fixLayout();
    setTimeout(fixLayout, 80);
  }

  setMode(currentMode, false);

  // 실시간 1:1 손가락 추적 + 손 놓았을 때 제자리 착 스냅 물리 엔진
  var touchStartY = 0;
  var startHeight = 0;
  var isDragging = false;
  var moveHistory = [];
  var isTouchOnKey = false;

  function onTouchStart(e) {
    if (e.touches.length !== 1) return;
    if (e.target.classList && e.target.classList.contains('agl-k')) {
      isTouchOnKey = true;
      return;
    }
    isTouchOnKey = false;
    touchStartY = e.touches[0].clientY;
    startHeight = MODE_HEIGHTS[currentMode];
    isDragging = true;
    moveHistory = [{ y: touchStartY, t: performance.now() }];

    if (ctrlContainer) {
      ctrlContainer.style.transition = 'none';
      ctrlContainer.style.display = 'block';
      ctrlContainer.style.height = startHeight + 'px';
    }
  }

  function onTouchMove(e) {
    if (!isDragging || isTouchOnKey || e.touches.length !== 1) return;
    var currentY = e.touches[0].clientY;
    var now = performance.now();
    var dy = currentY - touchStartY; // 위로 이동: dy < 0, 아래로 이동: dy > 0

    // 위로 당기면 높이 증가, 아래로 밀면 높이 감소
    var rawHeight = startHeight - dy;

    // 쫀득한 고무줄 저항감 (0 미만 또는 88 초과 시 감쇠)
    var h = rawHeight;
    if (h < 0) {
      h = h * 0.25;
    } else if (h > 88) {
      h = 88 + (h - 88) * 0.25;
    }
    var clampedH = Math.max(0, Math.min(98, h));

    if (ctrlContainer) {
      ctrlContainer.style.height = clampedH + 'px';
      if (pageRow) pageRow.style.display = (clampedH >= 73) ? 'flex' : 'none';
      if (clampedH < 44) {
        if (grid2Row) grid2Row.style.display = 'none';
        if (grid1Row) grid1Row.style.display = 'flex';
      } else {
        if (grid1Row) grid1Row.style.display = 'none';
        if (grid2Row) grid2Row.style.display = 'flex';
      }
    }

    moveHistory.push({ y: currentY, t: now });
    while (moveHistory.length > 0 && now - moveHistory[0].t > 100) {
      moveHistory.shift();
    }

    if (e.cancelable) e.preventDefault();
  }

  function onTouchEnd(e) {
    if (!isDragging || isTouchOnKey) return;
    isDragging = false;

    var endY = (e.changedTouches && e.changedTouches[0]) ? e.changedTouches[0].clientY : touchStartY;
    var now = performance.now();
    while (moveHistory.length > 0 && now - moveHistory[0].t > 100) {
      moveHistory.shift();
    }

    // 플릭(flick) 방출 속도 계산 (px/ms)
    var releaseV = 0;
    if (moveHistory.length >= 2) {
      var oldest = moveHistory[0];
      var newest = moveHistory[moveHistory.length - 1];
      var dt = newest.t - oldest.t;
      if (dt > 0) {
        releaseV = (oldest.y - newest.y) / dt; // 위로 플릭하면 양수, 아래는 음수
      }
    }

    var currentH = startHeight - (endY - touchStartY);
    var targetMode = currentMode;

    if (releaseV > 0.3) {
      // 위로 튕김 -> 다음 단계로 확장
      targetMode = Math.min(3, currentMode + 1);
    } else if (releaseV < -0.3) {
      // 아래로 튕김 -> 이전 단계로 축소
      targetMode = Math.max(0, currentMode - 1);
    } else {
      // 손을 놓은 현재 높이 위치에 가장 가까운 슬롯으로 착 스냅
      if (currentH < 15) {
        targetMode = 0;
      } else if (currentH < 44) {
        targetMode = 1;
      } else if (currentH < 73) {
        targetMode = 2;
      } else {
        targetMode = 3;
      }
    }

    snapToMode(targetMode);
  }

  function snapToMode(targetMode) {
    var targetH = MODE_HEIGHTS[targetMode];
    if (ctrlContainer) {
      ctrlContainer.style.transition = 'height 0.22s cubic-bezier(0.2, 0.9, 0.3, 1)';
      ctrlContainer.style.height = targetH + 'px';
      if (grid1Row) grid1Row.style.display = (targetMode === 1) ? 'flex' : 'none';
      if (grid2Row) grid2Row.style.display = (targetMode === 2 || targetMode === 3) ? 'flex' : 'none';
      if (pageRow) pageRow.style.display = (targetMode === 3) ? 'flex' : 'none';
    }

    setTimeout(function() {
      setMode(targetMode);
    }, 230);
  }

  if (handleBar) {
    handleBar.addEventListener('touchstart', onTouchStart, { passive: false });
    handleBar.addEventListener('touchmove', onTouchMove, { passive: false });
    handleBar.addEventListener('touchend', onTouchEnd, { passive: true });
    handleBar.addEventListener('touchcancel', onTouchEnd, { passive: true });
    // 탭 전환 없음: 드래그로만 0~3줄 조절
  }

  if (ctrlContainer) {
    ctrlContainer.addEventListener('touchstart', onTouchStart, { passive: false });
    ctrlContainer.addEventListener('touchmove', onTouchMove, { passive: false });
    ctrlContainer.addEventListener('touchend', onTouchEnd, { passive: true });
    ctrlContainer.addEventListener('touchcancel', onTouchEnd, { passive: true });
  }

  var fileInput     = document.getElementById('agl-file-input');
  var attachBtn     = document.getElementById('agl-attach-btn');
  var previewBar    = document.getElementById('agl-preview-bar');
  var previewMedia  = document.getElementById('agl-preview-media');
  var previewName   = document.getElementById('agl-preview-name');
  var previewSize   = document.getElementById('agl-preview-size');
  var previewCancel = document.getElementById('agl-preview-cancel');
  var pendingFile   = null;
  var isSending     = false;

  function formatFileSize(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function setPendingFile(file) {
    if (!file) return;
    pendingFile = file;
    previewName.textContent = file.name || '첨부 파일';
    previewSize.textContent = formatFileSize(file.size);
    previewMedia.innerHTML = '';
    if (file.type && file.type.startsWith('image/')) {
      var img = document.createElement('img');
      img.className = 'agl-preview-thumb';
      img.src = URL.createObjectURL(file);
      previewMedia.appendChild(img);
    } else {
      var icon = document.createElement('div');
      icon.className = 'agl-preview-icon';
      icon.textContent = '📄';
      previewMedia.appendChild(icon);
    }
    previewBar.style.display = 'flex';
  }

  function clearPendingFile() {
    pendingFile = null;
    if (fileInput) fileInput.value = '';
    if (previewBar) previewBar.style.display = 'none';
    if (previewMedia) previewMedia.innerHTML = '';
  }

  if (attachBtn) {
    attachBtn.addEventListener('click', function(e) {
      e.preventDefault();
      fileInput.click();
    });
  }

  if (previewCancel) {
    previewCancel.addEventListener('click', function(e) {
      e.preventDefault();
      clearPendingFile();
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', function() {
      if (fileInput.files && fileInput.files[0]) {
        setPendingFile(fileInput.files[0]);
      }
    });
  }

  // 드래그 앤 드롭 및 클립보드 붙여넣기 지원
  window.addEventListener('dragover', function(e) { e.preventDefault(); });
  window.addEventListener('drop', function(e) {
    e.preventDefault();
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setPendingFile(e.dataTransfer.files[0]);
    }
  });
  window.addEventListener('paste', function(e) {
    if (e.clipboardData && e.clipboardData.files && e.clipboardData.files.length > 0) {
      setPendingFile(e.clipboardData.files[0]);
    }
  });

  // /input 엔드포인트로 HTTP POST — 프록시가 ttyd WebSocket에 직접 주입
  function sendToProxy(text) {
    return fetch('/input', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: text
    });
  }

  async function doSend() {
    if (isSending) return;
    var val = input.value || '';

    if (pendingFile) {
      isSending = true;
      var origText = sendBtn.textContent;
      sendBtn.textContent = '전송중...';
      sendBtn.disabled = true;

      var formData = new FormData();
      formData.append('file', pendingFile);

      try {
        var res = await fetch('/upload', {
          method: 'POST',
          body: formData
        });
        var data = await res.json();
        if (!res.ok || !data.path) {
          throw new Error(data.error || 'Upload failed');
        }

        var textContent = val.trim();
        var terminalMsg = textContent ? (data.path + ' ' + textContent) : data.path;

        input.value = '';
        clearPendingFile();
        await sendToProxy(terminalMsg + '\\r');
      } catch (err) {
        alert('파일 전송 실패: ' + err.message);
      } finally {
        isSending = false;
        sendBtn.textContent = origText;
        sendBtn.disabled = false;
      }
    } else {
      input.value = '';
      sendToProxy(val + '\\r');
      sendBtn.style.background = '#555';
      setTimeout(function() { sendBtn.style.background = ''; }, 120);
    }
  }

  // 키보드 Enter
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      doSend();
    }
  });

  // 전송 버튼 (click 이벤트)
  sendBtn.addEventListener('click', function(e) {
    e.preventDefault();
    doSend();
  });

  // 단축키 버튼 (키보드 팝업 방지를 위해 focus 호출 금지)
  var seqMap = {
    'AGL': '\\x03\\x03\\x15agl\\r', 'ENTER': '\\r', 'TAB': '\\t', 'ESC': '\\x1b',
    'UP': '\\x1b[A', 'DOWN': '\\x1b[B', 'LEFT': '\\x1b[D', 'RIGHT': '\\x1b[C',
    'PGUP': '\\x1b[5~', 'PGDN': '\\x1b[6~'
  };
  document.querySelectorAll('.agl-k').forEach(function(btn) {
    if (btn.id === 'agl-open-modal') return;
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var seq = seqMap[btn.dataset.seq] || '';
      if (seq) sendToProxy(seq);
    });
  });

  // 글자 크기 조절 (ttyd xterm 런타임 옵션 직접 변경, 재접속 불필요)
  var DEFAULT_FONT = 8; // ttyd-start.sh -t fontSize=8 과 동일
  function getFontSize() {
    try {
      if (window.term && window.term.options && window.term.options.fontSize) {
        return window.term.options.fontSize;
      }
    } catch (e) {}
    try {
      var s = localStorage.getItem('agy_fontsize');
      if (s) return parseInt(s, 10) || DEFAULT_FONT;
    } catch (e) {}
    return DEFAULT_FONT;
  }
  function setFontSize(n) {
    n = Math.max(6, Math.min(30, n));
    try { localStorage.setItem('agy_fontsize', String(n)); } catch (e) {}
    try {
      if (window.term) window.term.setOption('fontSize', n);
    } catch (e) {}
    fixLayout(); // 뒤따르는 resize 1회로 refit+행열조정까지 한 번에
  }
  // 글자 크기: 연타 누적 후 250ms 뒤 한 번에 적용 (refit 1회)
  var fontPending = null;
  var fontCommitT = null;
  var fontFlashT = null;
  function commitFontSize() {
    fontCommitT = null;
    if (fontPending === null) return;
    var n = fontPending;
    fontPending = null;
    var liveOk = false;
    try {
      if (window.term && typeof window.term.setOption === 'function') {
        window.term.setOption('fontSize', n);
        liveOk = true;
      }
    } catch (err) { liveOk = false; }
    setTimeout(function() {
      var cur = null;
      try { cur = window.term && window.term.options ? window.term.options.fontSize : null; }
      catch (e3) {}
      if (liveOk && cur === n) {
        fixLayout();
      } else {
        var url = new URL(window.location.href);
        url.searchParams.set('fontSize', String(n));
        window.location.href = url.toString();
      }
    }, 400);
  }
  document.querySelectorAll('.agl-k-font').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var mode = btn.dataset.font;
      var base = (fontPending !== null) ? fontPending : getFontSize();
      var n;
      if (mode === 'inc') n = base + 1;
      else if (mode === 'dec') n = base - 1;
      else n = DEFAULT_FONT;
      fontPending = Math.max(6, Math.min(30, n));
      try { localStorage.setItem('agy_fontsize', String(fontPending)); } catch (e2) {}
      // 누른 버튼에 누적 중인 크기 즉시 표시
      if (!btn.dataset.label) btn.dataset.label = btn.textContent;
      btn.textContent = fontPending;
      clearTimeout(fontFlashT);
      fontFlashT = setTimeout(function() {
        document.querySelectorAll('.agl-k-font').forEach(function(b) {
          if (b.dataset.label) b.textContent = b.dataset.label;
        });
      }, 800);
      clearTimeout(fontCommitT);
      fontCommitT = setTimeout(commitFontSize, 250);
    });
  });
  // 로드 시 저장된 글자 크기 복원 (ttyd 초기화 대기, 최대 5초)
  (function() {
    var tries = 0;
    var timer = setInterval(function() {
      tries++;
      if (window.term || tries > 10) {
        clearInterval(timer);
        try {
          var s = localStorage.getItem('agy_fontsize');
          if (s) setFontSize(parseInt(s, 10) || DEFAULT_FONT);
        } catch (e) {}
      }
    }, 500);
  })();

  // iOS 터치 스크롤: 스와이프 → tmux 스크롤 / 텍스트 선택 중에는 스크롤 차단
  function initTouchScroll() {
    var tc = document.getElementById('terminal-container');
    if (!tc) return;
    var startY = 0;
    var startX = 0;
    var lastY = 0;
    var lastTime = 0;
    var isTouching = false;
    var isScrolling = false;
    var accum = 0;
    var ROW_PX = 15;
    var SCROLL_THRESHOLD = 8;

    var moveHistory = []; // 최근 100ms 간의 터치 기록 저장 (정확한 방출 속도 계산)
    var inertiaAnim = null;

    tc.addEventListener('touchstart', function(e) {
      if (inertiaAnim) {
        cancelAnimationFrame(inertiaAnim);
        inertiaAnim = null;
      }
      if (e.touches.length === 1) {
        startY = e.touches[0].clientY;
        startX = e.touches[0].clientX;
        lastY = startY;
        lastTime = performance.now();
        accum = 0;
        moveHistory = [{ y: startY, t: lastTime }];
        isTouching = true;
        isScrolling = false;
      }
    }, { passive: true });

    tc.addEventListener('touchmove', function(e) {
      if (!isTouching || e.touches.length !== 1) return;

      // 텍스트 선택 영역이 잡혀있을 때만 스크롤 방지
      var sel = window.getSelection();
      if (sel && sel.toString().length > 0) {
        isScrolling = false;
        return;
      }

      var currentY = e.touches[0].clientY;
      var currentTime = performance.now();
      var dy = lastY - currentY;
      var totalDY = Math.abs(currentY - startY);
      var totalDX = Math.abs(e.touches[0].clientX - startX);

      if (!isScrolling && totalDY > SCROLL_THRESHOLD && totalDY > totalDX) {
        isScrolling = true;
      }

      if (!isScrolling) return;

      e.preventDefault();

      lastY = currentY;
      lastTime = currentTime;
      accum += dy;

      // 최근 100ms 내 터치 좌표 보관
      moveHistory.push({ y: currentY, t: currentTime });
      while (moveHistory.length > 0 && currentTime - moveHistory[0].t > 100) {
        moveHistory.shift();
      }

      var ROW_STEP = 15; // 저속 1:1 정밀 이동 (15px당 1줄)
      if (Math.abs(accum) >= ROW_STEP) {
        var dir = accum > 0 ? 1 : -1;
        var count = Math.floor(Math.abs(accum) / ROW_STEP);
        accum -= dir * count * ROW_STEP;

        var target = tc.querySelector('.xterm-screen') || tc;
        for (var i = 0; i < count; i++) {
          var ev = new WheelEvent('wheel', {
            bubbles: true,
            cancelable: true,
            deltaY: dir * 100,
            deltaMode: 0
          });
          target.dispatchEvent(ev);
        }
      }
    }, { passive: false });

    tc.addEventListener('touchend', function() {
      isTouching = false;
      isScrolling = false;
      accum = 0;

      var now = performance.now();
      // 최근 100ms 동안의 실질 이동 속도 계산
      while (moveHistory.length > 0 && now - moveHistory[0].t > 100) {
        moveHistory.shift();
      }

      if (moveHistory.length >= 2) {
        var oldest = moveHistory[0];
        var newest = moveHistory[moveHistory.length - 1];
        var dt = newest.t - oldest.t;
        var dy = oldest.y - newest.y; // 위로 스와이프하면 양수
        var releaseVelocity = dt > 0 ? (dy / dt) : 0; // px/ms

        // 플릭(flick) 시원하게 관성 발동
        if (Math.abs(releaseVelocity) > 0.35) {
          var v = releaseVelocity * 18;
          var friction = 0.935; // 자연스럽고 넉넉하게 이어지는 감속
          var inertiaAccum = 0;
          var lastFrameTime = performance.now();
          var target = tc.querySelector('.xterm-screen') || tc;

          function stepInertia(frameTime) {
            var frameDT = (frameTime - lastFrameTime) / 16.67;
            lastFrameTime = frameTime;
            if (frameDT > 3) frameDT = 1;

            v *= Math.pow(friction, frameDT);

            // 1.8 미만 속도에서 깔끔하게 정지
            if (Math.abs(v) < 1.8) {
              inertiaAnim = null;
              inertiaAccum = 0;
              return;
            }

            inertiaAccum += v * frameDT;
            var INERTIA_STEP = 15;
            if (Math.abs(inertiaAccum) >= INERTIA_STEP) {
              var dir = inertiaAccum > 0 ? 1 : -1;
              var count = Math.floor(Math.abs(inertiaAccum) / INERTIA_STEP);
              inertiaAccum -= dir * count * INERTIA_STEP;

              for (var i = 0; i < count; i++) {
                var ev = new WheelEvent('wheel', {
                  bubbles: true,
                  cancelable: true,
                  deltaY: dir * 100,
                  deltaMode: 0
                });
                target.dispatchEvent(ev);
              }
            }
            inertiaAnim = requestAnimationFrame(stepInertia);
          }
          inertiaAnim = requestAnimationFrame(stepInertia);
        }
      }
      moveHistory = [];
    }, { passive: true });

    tc.addEventListener('touchcancel', function() {
      isTouching = false;
      isScrolling = false;
      accum = 0;
      moveHistory = [];
      if (inertiaAnim) {
        cancelAnimationFrame(inertiaAnim);
        inertiaAnim = null;
      }
    }, { passive: true });
  }
  setTimeout(initTouchScroll, 500);

  // iOS 키보드 올라올 때 레이아웃 재조정 + 바 높이 바뀔 때마다 xterm에 refit 요청
  function fixLayout() {
    var vv = window.visualViewport;
    if (!vv) return;
    var bar = document.getElementById('agl-bar');
    var tc  = document.getElementById('terminal-container');
    if (!bar || !tc) return;
    tc.style.height = Math.max(vv.height - bar.getBoundingClientRect().height, 80) + 'px';
    // 컨테이너 높이 바꾼 뒤 ttyd 내장 fit이 돌도록 resize 통지 (디바운스)
    if (fixLayout._t) clearTimeout(fixLayout._t);
    fixLayout._t = setTimeout(function() {
      fixLayout._t = null;
      window.dispatchEvent(new Event('resize'));
    }, 120);
  }
  if (window.visualViewport) {
    window.visualViewport.addEventListener('resize', fixLayout);
    setTimeout(fixLayout, 500);
  }
})();
</script>
</body>
"""


async def handle_input(request):
    """브라우저 입력창 → ttyd WebSocket 직접 주입"""
    global active_ttyd_ws
    text = await request.text()
    if not active_ttyd_ws or active_ttyd_ws.closed:
        return web.Response(status=503, text='No active terminal session')
    try:
        payload = ('0' + text).encode('utf-8')
        await active_ttyd_ws.send_bytes(payload)
        return web.Response(status=200, text='ok')
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def handle_terminal_text(request):
    """현재 스크롤되어 화면에 보이는 터미널 화면(tmux visible pane)만 캡처하여 반환"""
    try:
        proc = await asyncio.create_subprocess_exec(
            TMUX_BIN, 'capture-pane', '-p', '-t', TMUX_SESSION,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        raw_text = stdout.decode('utf-8', errors='ignore')
        lines = [line.rstrip() for line in raw_text.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        cleaned = '\n'.join(lines)
        return web.Response(status=200, text=cleaned, content_type='text/plain', charset='utf-8')
    except Exception as e:
        return web.Response(status=500, text=f"캡처 실패: {e}", content_type='text/plain', charset='utf-8')


async def handle_kill_session(request):
    """서버는 유지하고 터미널 내부 프로세스만 깨끗한 새 쉘로 리셋"""
    global terminal_buffer
    try:
        shell = os.environ.get("SHELL", "zsh")
        cmd = (
            f"pkill -9 -f {TMUX_SESSION} 2>/dev/null; "
            f"{TMUX_BIN} respawn-pane -k -t {TMUX_SESSION} {shell} 2>/dev/null || "
            f"{TMUX_BIN} new-session -d -s {TMUX_SESSION} {shell} 2>/dev/null"
        )
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.wait()
        terminal_buffer.clear()
        return web.Response(status=200, text='Terminal respawned', content_type='text/plain')
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def proxy_websocket(request):
    global active_ttyd_ws, terminal_buffer
    ws_client = web.WebSocketResponse(protocols=['tty'])
    await ws_client.prepare(request)

    ttyd_url = f"ws://{TTYD_HOST}:{TTYD_PORT}/ws"
    skip = {'host', 'upgrade', 'connection', 'sec-websocket-key',
            'sec-websocket-version', 'sec-websocket-extensions'}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ttyd_url, headers=headers, protocols=['tty']) as ws_ttyd:
            active_ttyd_ws = ws_ttyd  # 활성 WebSocket 참조 저장

            async def client_to_ttyd():
                async for msg in ws_client:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        await ws_ttyd.send_bytes(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        await ws_ttyd.send_str(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break

            async def ttyd_to_client():
                async for msg in ws_ttyd:
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        if len(msg.data) > 1 and msg.data[0] in (0, ord('0')):
                            try:
                                text_chunk = msg.data[1:].decode('utf-8', errors='ignore')
                                terminal_buffer.append(text_chunk)
                            except Exception:
                                pass
                        await ws_client.send_bytes(msg.data)
                    elif msg.type == aiohttp.WSMsgType.TEXT:
                        if len(msg.data) > 1 and msg.data[0] in ('0', '\x00'):
                            terminal_buffer.append(msg.data[1:])
                        await ws_client.send_str(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                        break

            await asyncio.gather(client_to_ttyd(), ttyd_to_client())

    return ws_client


async def proxy_http(request):
    path = request.path_qs
    ttyd_url = f"http://{TTYD_HOST}:{TTYD_PORT}{path}"
    skip = {'host'}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}

    async with aiohttp.ClientSession() as session:
        async with session.request(
            request.method, ttyd_url,
            headers=headers,
            data=await request.read()
        ) as resp:
            ctype = resp.headers.get('Content-Type', '')
            body = await resp.read()

            if 'text/html' in ctype:
                html = body.decode('utf-8', errors='replace')
                html = re.sub(r'<meta[^>]*name=["\']viewport["\'][^>]*>', '', html)
                html = html.replace('<head>', '<head>' + HEAD_INJECT, 1)
                html = html.replace('</body>', BODY_INJECT, 1)
                body = html.encode('utf-8')

            resp_headers = {k: v for k, v in resp.headers.items()
                            if k.lower() not in ('content-length', 'transfer-encoding',
                                                  'content-encoding')}
            if 'text/html' in ctype:
                # 바 HTML은 항상 최신으로 (Safari 캐시로 옛날 바 보이는 문제 방지)
                resp_headers = {k: v for k, v in resp_headers.items()
                                if k.lower() not in ('etag', 'last-modified')}
                resp_headers['Cache-Control'] = 'no-store, max-age=0'
            return web.Response(status=resp.status, body=body, headers=resp_headers)


# Optional static assets (PWA icons). Missing files are simply skipped
# so the proxy runs fine without a system-wide ttyd data dir.
_TTYD_SHARE = os.environ.get("TTYD_SHARE_DIR", "/usr/local/share/ttyd")
STATIC_FILES = {
    path: (os.path.join(_TTYD_SHARE, name), ctype)
    for path, name, ctype in [
        ('/apple-touch-icon.png', 'apple-touch-icon.png', 'image/png'),
        ('/apple-touch-icon-precomposed.png', 'apple-touch-icon.png', 'image/png'),
        ('/favicon.png', 'favicon.png', 'image/png'),
        ('/favicon.ico', 'favicon.png', 'image/png'),
        ('/icon-512.png', 'icon-512.png', 'image/png'),
        ('/manifest.json', 'manifest.json', 'application/manifest+json'),
    ]
    if os.path.exists(os.path.join(_TTYD_SHARE, name))
}


async def handle_mouse_toggle(request):
    """tmux 마우스 모드를 on/off 토글하고 현재 상태를 반환"""
    try:
        # 현재 상태 확인
        proc = await asyncio.create_subprocess_exec(
            TMUX_BIN, 'show-option', '-g', 'mouse',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        current = stdout.decode().strip()  # e.g. "mouse on" or "mouse off"
        new_state = 'off' if 'on' in current else 'on'
        # 상태 전환
        proc2 = await asyncio.create_subprocess_exec(
            TMUX_BIN, 'set-option', '-g', 'mouse', new_state
        )
        await proc2.wait()
        return web.Response(status=200, text=new_state, content_type='text/plain')
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def handle_upload(request):
    """모바일/웹 파일 업로드 수신 -> UPLOAD_DIR에 저장 후 절대 경로 반환"""
    try:
        reader = await request.multipart()
        field = await reader.next()
        if not field:
            return web.json_response({'error': 'No file uploaded'}, status=400)

        filename = field.filename or 'upload'
        base, ext = os.path.splitext(filename)
        # 파일명 정리: 영문, 숫자, 한글, 언더스코어, 하이픈 외는 언더스코어로 치환
        safe_base = re.sub(r'[^\w\-]', '_', base)
        if not safe_base:
            safe_base = 'file'
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final_filename = f"{timestamp}_{safe_base}{ext}"
        save_path = os.path.join(UPLOAD_DIR, final_filename)

        with open(save_path, 'wb') as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)

        print(f"📥 파일 업로드 완료: {save_path} ({os.path.getsize(save_path)} bytes)")
        return web.json_response({
            'status': 'ok',
            'path': save_path,
            'filename': final_filename,
            'size': os.path.getsize(save_path)
        })
    except Exception as e:
        print(f"❌ 파일 업로드 실패: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def router(request):
    if request.path in STATIC_FILES:
        filepath, ctype = STATIC_FILES[request.path]
        return web.FileResponse(filepath, headers={'Content-Type': ctype, 'Cache-Control': 'public, max-age=86400'})
    if request.path == '/upload':
        return await handle_upload(request)
    if request.path == '/input':
        return await handle_input(request)
    if request.path == '/terminal_text':
        return await handle_terminal_text(request)
    if request.path == '/kill_session':
        return await handle_kill_session(request)
    if request.path == '/mouse_toggle':
        return await handle_mouse_toggle(request)
    if request.headers.get('Upgrade', '').lower() == 'websocket':
        return await proxy_websocket(request)
    return await proxy_http(request)


async def main():
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.router.add_route('*', '/{path_info:.*}', router)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PROXY_PORT).start()
    print(f"✅ 프록시 {PROXY_PORT} → ttyd {TTYD_PORT}")
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
