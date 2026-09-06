# ttyd-web-control 🖥️

> iPad / 모바일 브라우저에서 Mac의 `tmux` 및 터미널 환경을 완벽하게 제어하기 위한 웹 프록시 및 최적화 도구 세트

---

## ✨ 핵심 기능

- **iOS / iPad 최적화 웹 프록시 (`ttyd-proxy.py`)**:
  - **관성 스크롤(Inertia Scrolling)**: 터치 스와이프 감속 곡선 기반의 부드러운 스크롤 구현
  - **터치 제스처 락킹 방지**: Safari viewport 충돌 방지 및 1:1 정밀 터미널 탐색
  - **가상 단축키 툴바**: 모바일 화면에서 누르기 편한 2열 반응형 키보드 툴바 (Tab, Enter, Esc, 방향키 등)
  - **한글 입력 지원 & 텍스트 선택 모달**: 웹 터미널 환경에서의 텍스트 드래그 및 복사 지원

- **Antigravity Launcher CLI (`agl`)**:
  - 터미널 내부에서 키보드(방향키, Enter, Tab 새로고침, Esc)로 세션 및 설정을 전환하는 대화형 메뉴 UI

- **자동 세션 복구 및 데몬 구성 (`ttyd-start.sh`)**:
  - Mac 백그라운드 서비스 및 `tmux` 세션 자동 복구 구성

---

## 🛠 구성 요소

- `ttyd-proxy.py`: WebSocket/HTTP 중계 프록시 (aiohttp 기반)
- `agl`: CLI 런처 대화형 인터페이스
- `ttyd-start.sh`: 백그라운드 자동 실행 스크립트
- `.tmux.conf`: ttyd 웹 터미널 연동에 최적화된 tmux 환경설정
