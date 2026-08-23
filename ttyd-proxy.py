#!/usr/bin/env python3
"""
ttyd 원본 디자인 유지 + 한글 입력창 주입 프록시 + 100% 텍스트 복사/선택 모달.
- ttyd: 127.0.0.1:7682 (내부 전용)
- 프록시: 0.0.0.0:7681 (외부 노출)
"""

import asyncio
import aiohttp
from aiohttp import web
import re
from collections import deque

TTYD_HOST = "127.0.0.1"
TTYD_PORT = 7682
PROXY_PORT = 7681

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
    background: #1a1a1a;
    border-top: 1px solid #333;
    padding-bottom: env(safe-area-inset-bottom, 0px);
    width: 100%;
  }
  #agl-ctrl-row {
    display: flex;
    gap: 5px;
    padding: 6px 10px 4px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
  }
  #agl-ctrl-row::-webkit-scrollbar { display: none; }
  .agl-k {
    flex-shrink: 0;
    background: #2d2d2d;
    color: #ccc;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 5px 9px;
    font-size: 12px;
    font-family: 'Menlo', monospace;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
    min-height: 32px;
  }
  .agl-k:active { background: #555; color: #fff; }
  #agl-input-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 5px 8px 7px;
  }
  #agl-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
    background: #4af626;
    flex-shrink: 0;
    display: inline-block;
    margin-left: 2px;
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
  #agl-send:active { background: #555; }

</style>

<div id="agl-bar">
  <div id="agl-ctrl-row">
    <button class="agl-k" data-seq="AGL">agl</button>
    <button class="agl-k" data-seq="ENTER">Enter</button>
    <button class="agl-k" data-seq="TAB">Tab</button>
    <button class="agl-k" data-seq="ESC">Esc</button>
    <button class="agl-k" data-seq="UP">↑</button>
    <button class="agl-k" data-seq="DOWN">↓</button>
    <button class="agl-k" data-seq="LEFT">←</button>
    <button class="agl-k" data-seq="RIGHT">→</button>
  </div>
  <div id="agl-input-row">
    <span id="agl-dot" style="background:#38a169;"></span>
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
  var sendBtn = document.getElementById('agl-send');
  var input   = document.getElementById('agl-text');
  var dot     = document.getElementById('agl-dot');

  // /input 엔드포인트로 HTTP POST — 프록시가 ttyd WebSocket에 직접 주입
  function sendToProxy(text) {
    return fetch('/input', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      body: text
    }).then(function(r) {
      if (dot) dot.style.background = r.ok ? '#4af626' : '#ff4444';
    }).catch(function() {
      if (dot) dot.style.background = '#ff4444';
    });
  }

  function doSend() {
    var val = input.value || '';
    input.value = '';
    sendToProxy(val + '\\r');
    sendBtn.style.background = '#555';
    setTimeout(function() { sendBtn.style.background = ''; }, 120);
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
    'UP': '\\x1b[A', 'DOWN': '\\x1b[B', 'LEFT': '\\x1b[D', 'RIGHT': '\\x1b[C'
  };
  document.querySelectorAll('.agl-k').forEach(function(btn) {
    if (btn.id === 'agl-open-modal') return;
    btn.addEventListener('click', function(e) {
      e.preventDefault();
      var seq = seqMap[btn.dataset.seq] || '';
      if (seq) sendToProxy(seq);
    });
  });

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

    tc.addEventListener('touchstart', function(e) {
      if (e.touches.length === 1) {
        startY = e.touches[0].clientY;
        startX = e.touches[0].clientX;
        lastY = startY;
        lastTime = performance.now();
        accum = 0;
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
      var dt = currentTime - lastTime || 16;
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

      var ROW_STEP = 15; // 천천히 움직일 땐 15px당 1줄씩 정밀 이동
      if (Math.abs(accum) >= ROW_STEP) {
        var dir = accum > 0 ? 1 : -1;
        var count = Math.floor(Math.abs(accum) / ROW_STEP);
        accum -= dir * count * ROW_STEP;

        // 속도 계산 (px/ms)
        var speed = Math.abs(dy) / dt;
        if (speed > 1.8) {
          count = Math.min(count * 4, 12);
        } else if (speed > 1.0) {
          count = Math.min(count * 2, 6);
        }

        // ttyd xterm 스크린 요소 타깃팅
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

    tc.addEventListener('touchend', function() { isTouching = false; isScrolling = false; accum = 0; }, { passive: true });
    tc.addEventListener('touchcancel', function() { isTouching = false; isScrolling = false; accum = 0; }, { passive: true });
  }
  setTimeout(initTouchScroll, 500);

  // iOS 키보드 올라올 때 레이아웃 재조정
  function fixLayout() {
    var vv = window.visualViewport;
    if (!vv) return;
    var bar = document.getElementById('agl-bar');
    var tc  = document.getElementById('terminal-container');
    if (!bar || !tc) return;
    tc.style.height = Math.max(vv.height - bar.getBoundingClientRect().height, 80) + 'px';
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
            '/usr/local/bin/tmux', 'capture-pane', '-p', '-t', 'agy',
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
    """서버는 유지하고 터미널 내부 프로세스만 깨끗한 새 쉘(zsh)로 리셋"""
    global terminal_buffer
    try:
        cmd = """
        pkill -9 -f agy 2>/dev/null
        /usr/local/bin/tmux respawn-pane -k -t agy zsh 2>/dev/null || /usr/local/bin/tmux new-session -d -s agy zsh 2>/dev/null
        """
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
            return web.Response(status=resp.status, body=body, headers=resp_headers)


STATIC_FILES = {
    '/apple-touch-icon.png': ('/usr/local/share/ttyd/apple-touch-icon.png', 'image/png'),
    '/apple-touch-icon-precomposed.png': ('/usr/local/share/ttyd/apple-touch-icon.png', 'image/png'),
    '/favicon.png': ('/usr/local/share/ttyd/favicon.png', 'image/png'),
    '/favicon.ico': ('/usr/local/share/ttyd/favicon.png', 'image/png'),
    '/icon-512.png': ('/usr/local/share/ttyd/icon-512.png', 'image/png'),
    '/manifest.json': ('/usr/local/share/ttyd/manifest.json', 'application/manifest+json'),
}


async def handle_mouse_toggle(request):
    """tmux 마우스 모드를 on/off 토글하고 현재 상태를 반환"""
    try:
        # 현재 상태 확인
        proc = await asyncio.create_subprocess_exec(
            '/usr/local/bin/tmux', 'show-option', '-g', 'mouse',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        current = stdout.decode().strip()  # e.g. "mouse on" or "mouse off"
        new_state = 'off' if 'on' in current else 'on'
        # 상태 전환
        proc2 = await asyncio.create_subprocess_exec(
            '/usr/local/bin/tmux', 'set-option', '-g', 'mouse', new_state
        )
        await proc2.wait()
        return web.Response(status=200, text=new_state, content_type='text/plain')
    except Exception as e:
        return web.Response(status=500, text=str(e))


async def router(request):
    if request.path in STATIC_FILES:
        filepath, ctype = STATIC_FILES[request.path]
        return web.FileResponse(filepath, headers={'Content-Type': ctype, 'Cache-Control': 'public, max-age=86400'})
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
    app = web.Application()
    app.router.add_route('*', '/{path_info:.*}', router)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PROXY_PORT).start()
    print(f"✅ 프록시 {PROXY_PORT} → ttyd {TTYD_PORT}")
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
