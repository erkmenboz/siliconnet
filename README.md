# SiliconNet

**English** · [Türkçe](README.tr.md) · [Deutsch](README.de.md)

A local DPI bypass proxy for macOS. It runs on your own Mac, listens on
`127.0.0.1`, and routes the sites you configure through a local proxy that
fragments the TLS ClientHello so a deep-packet-inspection box cannot read the
server name and drop the connection.

![macOS 12+](https://img.shields.io/badge/macOS-12%2B-black)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)

## What it is for

Some networks block sites by looking at the `SNI` field of the TLS handshake —
the server name your browser sends in the clear before encryption starts — and
resetting the connection when it matches a blocklist. The same networks often
poison DNS so the domain resolves to a block page instead of the real server.

SiliconNet addresses both:

- **DNS over HTTPS.** Configured domains are resolved through an encrypted DoH
  resolver, so a poisoned local DNS answer is never used.
- **TLS record fragmentation.** The ClientHello is split across two TLS records,
  so a DPI box that scans a single record never sees the whole server name.
  Twenty-five strategies are available; the engine measures which one works on
  your network and keeps using it.

Only the sites you list go through the proxy. Everything else connects normally.

**This is not a VPN and not an anonymity tool.** It does not hide your IP
address, and the site you visit still sees your real address. It only changes
how the connection is *opened* so that a filter in the middle cannot classify
it. Use it where you are allowed to.

## Requirements

| | |
|---|---|
| OS | macOS 12 Monterey or newer — **macOS only**, there is no Windows or Linux build |
| Python | 3.10+ (Homebrew, python.org, or Command Line Tools) |
| Privileges | None on an admin account; a standard account is prompted once by macOS |

The launcher installs the Python packages (`pystray`, `Pillow`, PyObjC) into a
local virtual environment. Nothing is installed system-wide, no daemon is added,
and nothing runs as root.

## Install

```bash
git clone https://github.com/erkmenboz/siliconnet.git
cd siliconnet
./siliconnet-launcher.sh
```

In Finder you can also double-click **`SiliconNet.command`**, which opens
Terminal and runs the same launcher.

The first run creates `.venv` and installs the requirements. If
`python3 -m venv` fails, install the Command Line Tools:

```bash
xcode-select --install
```

If you downloaded a release archive instead of cloning, macOS may quarantine it:

```bash
xattr -dr com.apple.quarantine siliconnet-macos-<version>
```

## Use it

Once it is running:

- The **menu bar icon** appears at the top right, next to Wi-Fi and the clock.
  A single click opens the menu — status, ping, dashboard, restart, exit.
- The **dashboard** is at **<http://127.0.0.1:8888>**.

In the dashboard you can add the domains you want routed, watch which strategy
is winning, and switch language (EN/TR/DE) and appearance (light/dark).

**To start automatically at login:** dashboard → **Settings** → **Auto-start**.
This installs a user LaunchAgent in `~/Library/LaunchAgents`. Keep the project
folder where it is afterwards — the agent stores its full path.

**To stop:** menu bar → **Exit**. Closing the Terminal window is not enough;
your system proxy settings need to be restored on the way out.

## How it works

SiliconNet writes the HTTP and HTTPS proxy of every enabled network service with
the built-in `networksetup` tool, backs up the previous values to
`macos_proxy_state.json`, and restores them when it stops.

On most personal Macs the logged-in user is an administrator and `networksetup`
applies the change without a password. If macOS refuses — a standard account, or
"require an administrator password to change settings" — the same batch is
replayed once through `osascript … with administrator privileges`, which shows
the native password dialog. Cancelling it leaves your settings untouched.

Some apps embed their own HTTP stack and ignore the macOS proxy entirely
(Discord's updater is the usual case). While SiliconNet owns the proxy it also
publishes `HTTP_PROXY`/`HTTPS_PROXY` into the launchd session, so apps launched
afterwards can reach it. Both are undone on exit.

### Where your data lives

```text
~/Library/Application Support/SiliconNet
```

| File | Purpose |
|---|---|
| `config.json` | Sites, ports, privacy and performance settings |
| `bypass.log` | Warning/error log (set `DPI_BYPASS_LOG_LEVEL=INFO` for detail) |
| `macos_proxy_state.json` | Your previous proxy state, restored on exit |
| `strategy_cache.json` | Which strategy works for which site |
| `ai_strategy.json` | Adaptive strategy learning data |
| `stats.json` | Runtime counters |

LaunchAgent logs go to `~/Library/Logs/SiliconNet/`. Nothing is sent anywhere;
all of it stays on your Mac. See [PRIVACY.md](PRIVACY.md).

## Troubleshooting

**No internet after SiliconNet stopped unexpectedly.** Your system proxy may
still point at a port nothing is listening on. Start SiliconNet again — it
detects and clears a stale setting on startup — or turn the proxy off manually:

```bash
networksetup -setwebproxystate Wi-Fi off
networksetup -setsecurewebproxystate Wi-Fi off
```

**A site still does not open.** Apps started *before* the proxy was enabled may
not have picked it up; quit and reopen the app. Browsers read the proxy setting
at launch, so quit the browser fully (⌘Q) rather than just closing the window.

**No menu bar icon.** It needs `pystray`, `Pillow` and PyObjC, which the
launcher installs into `.venv`. If you start the app with a different
interpreter, the icon is skipped and everything else still works. On a MacBook
with a notch, a crowded menu bar can also push the icon out of sight — the
dashboard is still reachable at the address above.

**See what it is doing.** Start with `DPI_BYPASS_LOG_LEVEL=INFO
./siliconnet-launcher.sh`, or open the **Logs** tab in the dashboard.

## Build and verify

```bash
./run_tests.sh                      # test suite
scripts/build_macos_release.sh      # clean tarball in dist/
scripts/verify_macos_release.sh     # tests + packaging checks
```

## Credits and license

SiliconNet is MIT licensed.

Its proxy core, strategy engine, and dashboard are derived from
CleanNet (MIT, Copyright © 2026 digaxie).
The original copyright notice is kept in [LICENSE](LICENSE), and the split
between upstream and this project is spelled out in [NOTICE](NOTICE).

The macOS integration layer is written for this project: `networksetup` proxy
management, the LaunchAgent autostart, the `lsof` flow parser, the menu bar
item, and the environment compatibility layer.
