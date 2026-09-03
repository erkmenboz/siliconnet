# SiliconNet

SiliconNet is a local DPI bypass proxy for macOS. It listens on `127.0.0.1`, routes selected HTTPS connections through a local proxy, and can fragment TLS ClientHello traffic for configured sites.

**macOS only.** There is no Windows or Linux build. The launcher refuses to start on anything but Darwin, and the OS integration is written directly against `networksetup`, `launchctl`, `lsof`, and `osascript`.

## Requirements

| | |
|---|---|
| OS | macOS 12 Monterey or newer |
| Python | 3.10+ (Homebrew, python.org, or Command Line Tools) |
| Python packages | `pystray`, `Pillow`, `pyobjc-framework-Cocoa`, `pyobjc-framework-Quartz` — installed by the launcher |
| Privileges | None for an admin account; a standard account is prompted once by macOS when the proxy is enabled |

## What Works

- Core proxy, DNS over HTTPS, strategy selection, AI strategy cache, and dashboard.
- System proxy settings are managed with the built-in `networksetup` tool, applied to every enabled network service (Wi-Fi, Ethernet, …).
- Autostart uses a user-level LaunchAgent in `~/Library/LaunchAgents`; no root daemon is installed.
- The menu bar item uses `pystray` (a native `NSStatusItem` through PyObjC); confirmation dialogs use `osascript`.
- Network-flow diagnostics use the built-in `lsof`; if it is unavailable, only that dashboard feature is disabled.

## Install And Run

```bash
tar -xzf siliconnet-macos-<version>.tar.gz
cd siliconnet-macos-<version>
./siliconnet-launcher.sh
```

In Finder you can also double-click `SiliconNet.command`, which opens Terminal and runs the same launcher.

Then open:

```text
http://127.0.0.1:8888
```

The first launch creates a virtual environment in `.venv` and installs the requirements. If `python3 -m venv` fails, install the Command Line Tools:

```bash
xcode-select --install
```

Manual run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m siliconnet
```

## Gatekeeper Note

The tarball is unsigned. macOS quarantines files downloaded with a browser, so the first `./siliconnet-launcher.sh` may be blocked. Clear the quarantine flag on the extracted folder:

```bash
xattr -dr com.apple.quarantine siliconnet-macos-<version>
```

## Data Locations

SiliconNet stores runtime data under:

```text
${SILICONNET_DATA_DIR}
~/Library/Application Support/SiliconNet
```

Typical files:

| File | Purpose |
|---|---|
| `config.json` | Sites, ports, privacy/performance settings |
| `bypass.log` | Warning/error disk log |
| `macos_proxy_state.json` | Previous proxy state of every network service while SiliconNet owns proxy settings |
| `strategy_cache.json` | Learned strategy cache |
| `ai_strategy.json` | Adaptive strategy learning data |
| `stats.json` | Runtime counters |

LaunchAgent logs go to `~/Library/Logs/SiliconNet/`.

## Proxy Behavior

SiliconNet writes the HTTP and HTTPS proxy of your enabled network services and their bypass domains, then restores the previous values from `macos_proxy_state.json` when it stops or when the proxy is turned off from the dashboard or menu bar.

On most personal Macs the logged-in user is an administrator and `networksetup` applies the change without a password. If macOS refuses it — a standard user account, or the "require an administrator password to change settings" option — the same batch of commands is replayed once through `osascript … with administrator privileges`, which shows the native password dialog. Cancelling that dialog leaves your settings untouched and SiliconNet reports the failure.

SiliconNet never installs a daemon, never edits `/Library` or `/etc`, and never runs anything as root outside that single authorized batch.

## Menu Bar Notes

SiliconNet lives in the menu bar, at the top right next to Wi-Fi and the clock. **A single click opens the menu** — macOS does not use the separate right-click menu that Windows tray icons have:

```text
SiliconNet v1.0
─────────────────
Status: Active
Ping: 21ms
─────────────────
Dashboard
Refresh IPs
Log File
─────────────────
Restart
Exit
Full Shutdown (Reset Network)
```

Status and ping are rebuilt every two seconds from a run loop timer, so they are current when you open the menu.

SiliconNet runs as an accessory app: no Dock tile and no entry in the app switcher, the same as any other menu bar utility. The dashboard opens in your browser at `http://127.0.0.1:8888`, "Log File" opens the log in TextEdit.

The menu bar item is optional. It needs `pystray`, `Pillow`, and PyObjC, which the launcher installs. If they are unavailable, SiliconNet keeps running and the dashboard remains reachable at the address above.

"Full Shutdown (Reset Network)" stops the proxy, restores your proxy settings, and flushes the DNS cache with `dscacheutil -flushcache`. The follow-up `killall -HUP mDNSResponder` only takes effect when SiliconNet runs as root, so it is a harmless no-op in normal use.

### Icons

`assets/siliconnet_tray.png` is the artwork alone — black pixels on a transparent plate — supplied to macOS as a template image at twice the point size. macOS draws it dark on a light menu bar, inverts it to white on a dark one, and Retina displays get the full pixel detail. `assets/siliconnet_app.png` keeps the logo on its rounded plate.

On a MacBook with a notch, a crowded menu bar can push items behind it. If the icon is not visible, the dashboard is still at `http://127.0.0.1:8888`.

## Build And Verify

Run tests:

```bash
./run_tests.sh
```

Build a clean tarball:

```bash
scripts/build_macos_release.sh
```

Full verification:

```bash
scripts/verify_macos_release.sh
```

## Credits And License

SiliconNet is MIT licensed. Its proxy core, strategy engine, and dashboard are derived from CleanNet (MIT, Copyright (c) 2026 digaxie); the original notice is kept in `LICENSE`. The macOS integration layer — `networksetup` proxy management, the LaunchAgent autostart, the `lsof` flow parser, and the menu bar item — is written for this project.

## Türkçe Kısa Not

SiliconNet macOS sürümü `python -m siliconnet` ile çalışır; Finder'dan `SiliconNet.command` dosyasına çift tıklayarak da açabilirsin. Proxy ayarlarını `networksetup` ile etkin ağ servislerine (Wi-Fi, Ethernet) yazar ve çıkarken eski haline döndürür. Standart kullanıcı hesaplarında macOS parola sorabilir; bu, sistemin kendi yönetici penceresidir. Veriler `~/Library/Application Support/SiliconNet` klasöründe tutulur. İnternetten indirdiğin arşiv açılmazsa `xattr -dr com.apple.quarantine siliconnet-macos-<sürüm>` komutunu çalıştır.
