# Changelog

## 2.1.4 - 2026-09-02

First SiliconNet release. macOS only: there is no Windows or Linux build, and no shared code path with one.

- Renamed the project to SiliconNet. The Python package is `siliconnet`, the entry point is `python -m siliconnet`, user data lives in `~/Library/Application Support/SiliconNet`, and the data-directory override is `SILICONNET_DATA_DIR`.
- System proxy is managed with `networksetup` across every enabled network service, with the previous state backed up to `macos_proxy_state.json` and restored on exit.
- Single admin fallback: when `networksetup` is refused, the same command batch is replayed once through `osascript … with administrator privileges`.
- Autostart uses a user LaunchAgent (`~/Library/LaunchAgents/com.siliconnet.SiliconNetDPIBypass.plist`) loaded with `launchctl bootstrap`, falling back to `launchctl load -w` on older systems.
- Network diagnostics use an `lsof` based flow parser; the dashboard reports the managed network services.
- Menu bar item uses pystray's native macOS backend, confirmation dialogs use `osascript`, and the full shutdown flushes DNS with `dscacheutil -flushcache`.
- New logo. `assets/siliconnet_app.png` is the full mark; `assets/siliconnet_tray.png` is a transparent template icon that macOS inverts for a dark menu bar, which pystray does not request on its own.
- Ships `SiliconNet.command` for Finder, `siliconnet-launcher.sh`, and the macOS build/verify release scripts.
- Removed every non-macOS remnant: registry-style autostart naming, the Windows-only `SIGBREAK` handler, UWP regression guards, and PyInstaller/installer artifacts from the packaging and ignore rules.

Carried over from the proxy core this release is built on: upstream connections use Happy Eyeballs (RFC 8305), racing IPv6 and IPv4 with a 250 ms stagger, so dual-stack sites no longer hang on networks that advertise but cannot route IPv6. Plain-HTTP passthrough is not DoH-resolved or blocked, so privacy mode applies to configured bypass sites only.
