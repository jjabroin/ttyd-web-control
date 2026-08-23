#!/bin/zsh
# ttyd + proxy + tmux 세션 유지 자동 시작 스크립트
export LANG=ko_KR.UTF-8
export LC_ALL=ko_KR.UTF-8
export PATH="/usr/local/bin:/Users/leeseungyoon/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

# 이전 프로세스 정리
pkill -f "ttyd.*7682" 2>/dev/null
pkill -f "ttyd-proxy.py" 2>/dev/null
sleep 1

# ttyd + tmux 자동 세션 복구 모드로 시작 (DOM 렌더러로 텍스트 선택 지원)
/usr/local/bin/ttyd -p 7682 --interface 127.0.0.1 -W -t fontSize=8 -t rendererType=dom tmux new-session -A -s agy zsh &
sleep 2

# 프록시 시작
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python /usr/local/bin/ttyd-proxy.py
