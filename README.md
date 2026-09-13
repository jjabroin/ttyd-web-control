# ttyd-web-control 📱🖥️

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-supported-black?logo=apple)](https://www.apple.com/macos/)
[![Linux](https://img.shields.io/badge/Linux-supported-yellow?logo=linux)](https://www.linux.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/jjabroin/ttyd-web-control/pulls)

Control your Mac/Linux **tmux terminal from iPhone/iPad Safari** — with inertia touch scrolling, a thumb-friendly shortcut bar, Korean input, page scrolling for fullscreen TUIs ([opencode](https://github.com/anomalyco/opencode), vim, htop…), live font-size controls, and photo/file upload — all on top of stock [ttyd](https://github.com/tsl0922/ttyd).

> 👀 **[Live look, no install](https://jjabroin.github.io/ttyd-web-control/)** — a static mock of the phone screen (non-interactive). The real thing is a plain **web app**: nothing to install on the phone, just open the URL in any modern mobile browser.

### 📎 Your phone becomes a cloud-like frontend for terminal AI

No broken-CJK needed to love this: tap **`+`**, pick a photo or file, and it's beamed into `~/ttyd-uploads` with its path typed into the terminal for you — like attaching a file in a cloud AI chat app, but the "cloud" is your own machine running **opencode / Claude Code / Gemini CLI**. Screenshot an error on the go → send it straight into your coding agent's prompt. Review a generated image without leaving the couch. That loop alone is worth the install.

> 🇰🇷 한국어 요약: iPad/모바일 브라우저에서 Mac의 tmux 터미널을 완벽 제어하기 위한 ttyd 웹 프록시 세트. 아래 한 줄 설치로 바로 시작하세요.

---

## ✨ Features

| Area | What you get |
|---|---|
| 📜 Touch scrolling | Swipe with inertia + flick physics, converted to precise wheel events (15px = 1 line) |
| ⌨️ Shortcut bar (0–3 rows) | Pull the handle: `0 / 1 / 2 / 3` rows. Esc, Tab, Enter, inverted-T arrows |
| 📄 Page row (3rd row) | `PgUp`/`PgDn` buttons that work **inside fullscreen TUIs** (opencode chat scrolls even while typing) |
| 🔠 Font controls | `A+` / `A−` / reset — live `xterm` font resize, no reconnect, saved per browser |
| 🇰🇷 Korean input | Dedicated input row with proper IME handling (`enterkeyhint=send`) |
| 📎 Uploads | **`+` button = attach files to your terminal AI like a cloud chat app.** Photo/file picker with KakaoTalk-style preview → saved to `~/ttyd-uploads`, path auto-typed into the prompt. Feed screenshots to opencode/Claude Code from your phone |
| 🖱️ tmux tuning | Mouse mode + 10k scrollback + 1:1 wheel bindings (ships as default `~/.tmux.conf`) |
| 🔌 Helper API | `/input` (keystroke injection), `/upload`, `/terminal_text`, `/mouse_toggle`, `/kill_session` |
| 🚀 Auto-start | LaunchAgent (macOS) / systemd user service (Linux) with auto-restart |

---

## 🚀 One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/jjabroin/ttyd-web-control/main/install.sh | bash
```

Then open **`http://<your-machine>:7681`** in mobile Safari. That's it.

> 🍎 **macOS point-and-click:** grab
> [`ttyd-web-control-0.1.0.dmg`](https://github.com/jjabroin/ttyd-web-control/releases/latest)
> from Releases, open it, double-click **`Install.command`** — Terminal runs the same installer above. No CLI typing needed.

Pair with [Tailscale](https://tailscale.com/) for secure iPhone/iPad access from anywhere (no port-forwarding).

### Options

```bash
# Custom ports / session / font size
PROXY_PORT=8080 TTYD_PORT=7683 TMUX_SESSION=main FONT_SIZE=10 \
  curl -fsSL https://raw.githubusercontent.com/jjabroin/ttyd-web-control/main/install.sh | bash

# Uninstall (keeps tmux sessions + uploads)
curl -fsSL https://raw.githubusercontent.com/jjabroin/ttyd-web-control/main/install.sh | bash -s -- --uninstall
```

<details>
<summary>Manual install (no script)</summary>

```bash
# 1. Dependencies: tmux, ttyd (https://github.com/tsl0922/ttyd), python3 + aiohttp
brew install tmux ttyd            # macOS
sudo apt install tmux python3 python3-pip  # Debian/Ubuntu (+ ttyd binary from releases)

python3 -m pip install --user aiohttp
git clone https://github.com/jjabroin/ttyd-web-control.git
cd ttyd-web-control
cp .tmux.conf ~/.tmux.conf        # skip if you have your own
./ttyd-start.sh                   # ttyd :7682 (internal) + proxy :7681 (public)
```

</details>

---

## 📖 Usage

1. **Connect** — Safari (or any modern mobile browser — it's just a web app, zero phone-side install) → `http://<machine>:7681`
2. **Pull the handle** — `0` hidden · `1` compact · `2` full keys · `3` page-scroll row stacked on top (drag only, no tap-cycling)
3. **Scroll chats** — in opencode/vim-like fullscreen apps, use the 3rd-row `PgUp`/`PgDn` (plain `↑/↓` stays as input history while typing — by design)
4. **Resize text** — `A+`/`A−` (rapid taps accumulate, applied once), `Reset` back to default
5. **Attach files** — `+` button → photo/library/file → path is typed into the terminal for you. Example flow with an AI agent: `opencode` → `+` → pick a screenshot → `what's wrong here?` → Enter. Your phone just became a mobile client for your home AI rig

> **opencode tip:** if wheel-swipe doesn't scroll the chat, keep opencode's `mouse: true` (default) and use the `PgUp`/`PgDn` row — synthetic wheels can't reach alt-screen app viewports through tmux, but injected `PgUp`/`PgDn` keys always can. See [Troubleshooting](#-troubleshooting).

---

## ⚙️ Configuration

Everything is env-driven — no code edits needed. Edit `~/.local/share/ttyd-web-control/.env`, then restart the service.

| Variable | Default | Meaning |
|---|---|---|
| `PROXY_PORT` | `7681` | Public port (open this in Safari) |
| `TTYD_PORT` | `7682` | Internal ttyd port (keep on loopback) |
| `TTYD_HOST` | `127.0.0.1` | ttyd bind interface |
| `TMUX_SESSION` | `agy` | Persistent tmux session name |
| `FONT_SIZE` | `8` | Startup terminal font size |
| `TTYD_UPLOAD_DIR` | `~/ttyd-uploads` | Upload destination |
| `TTYD_SHARE_DIR` | `/usr/local/share/ttyd` | Optional PWA icons (skipped if absent) |

Browser-persisted settings (per device): bar mode (`agl_bar_mode`), font size (`agy_fontsize`).

### HTTP API

| Endpoint | Method | Description |
|---|---|---|
| `/input` | POST `text/plain` | Inject keystrokes (`\r`, `\x1b[A`, `\x1b[5~`…) into the live pty |
| `/upload` | POST `multipart` | Save file → `{ "path": "~/ttyd-uploads/..." }` |
| `/terminal_text` | GET | Visible pane text via `tmux capture-pane` |
| `/mouse_toggle` | GET | Toggle tmux `mouse on/off`, returns new state |
| `/kill_session` | GET | Respawns the shell, keeps servers up |

---

## 🗂️ Project structure

```
ttyd-web-control/
├── install.sh       # one-touch installer (macOS brew / Debian / Fedora) + --uninstall
├── ttyd-proxy.py    # aiohttp reverse proxy: control-bar injection, touch→wheel,
│                    #   font-size API, uploads, helper endpoints (all env-configurable)
├── ttyd-start.sh    # portable launcher: ttyd + tmux -A + proxy (foreground for supervisors)
├── .tmux.conf       # mouse on, 10k scrollback, 1:1 wheel bindings
└── LICENSE          # MIT
```

### How scrolling works

Mobile Safari can't wheel-scroll `xterm` reliably, so the proxy layers three mechanisms:

1. **Normal shell** — touch drags become synthetic `WheelEvent`s → tmux `mouse on` → `copy-mode` scrollback.
2. **Fullscreen TUIs** (alt-screen: opencode/vim) — wheels would be swallowed, so the 3rd-row buttons inject real `PgUp`/`PgDn` (`\x1b[5~`/`\x1b[6~`) via `/input`, which TUIs honor even with focused inputs.
3. **Layout sync** — every bar resize re-measures the bar and dispatches `resize` so ttyd re-fits rows/cols (single-pass, no flicker loop).

---

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| Old bar after update | Hard refresh. HTML is served `no-store`, but bust once via `http://host:7681/?v=2` |
| `tmux: syntax error` on swipe | A stale root `WheelUpPane` binding with `{ ... }` groups — this tmux version only parses plain commands. Re-run `install.sh` or reset with `tmux source-file ~/.tmux.conf` + re-bind |
| Arrows show input history in opencode | Expected: arrows belong to the prompt while typing. Use the `PgUp` row for chat scroll |
| Font buttons do nothing | Check the button flashes a number; if the page reloads instead, live `window.term` apply fell back to `?fontSize=` — still correct, just slower |
| Port in use (`Errno 48`) | A previous proxy is still bound: `lsof -i :7681` → `kill <pid>` (the LaunchAgent/systemd unit restarts it) |
| Service won't start at boot (Linux) | `loginctl enable-linger $USER`, then `systemctl --user restart ttyd-web-control` |

---

## 🗺️ Roadmap

- [ ] Screenshots + demo GIF in README
- [ ] Auto-show page row only when a fullscreen app is detected (`#{alternate_on}` polling)
- [ ] Optional Basic-Auth / token gate on the proxy
- [ ] Homebrew formula + AUR package

---

## 🤝 Contributing

PRs welcome! Keep it dependency-light (stdlib + `aiohttp`), test on real iOS Safari, and match the existing `feat:/fix:/chore:` commit style.

## 📄 License

[MIT](LICENSE) © 2026 jjabroin
