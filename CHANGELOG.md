# Changelog

## 1.0 - 2026-09-03

First working macOS release. Version reset to 1.0: the numbering inherited from
the upstream project did not describe this codebase, and nothing before this
point ran end to end on macOS.

- TLS *record* fragmentation is the SNI shield default. Measured against an ISP
  that blocks by SNI, plain TCP segmentation (`host_split`) is reassembled by
  the DPI and fails; splitting the ClientHello across two records succeeds.
- Proxy environment variables are published into the launchd session, so apps
  with embedded HTTP stacks that ignore the macOS proxy (Discord's updater)
  still reach the proxy.
- SIGTERM is honored while the menu bar item owns the main thread, so logout
  and `launchctl bootout` restore the system proxy instead of leaking it.
- Dashboard redrawn against the macOS palette: system colors, frosted toolbar,
  the app icon in the header, light and dark appearance, and no web-font fetch.
- Test runner and release verification use the virtualenv interpreter.

## 2.1.4 - 2026-09-02

First SiliconNet release. macOS only: there is no Windows or Linux build, and no shared code path with one.

- Renamed the project to SiliconNet. The Python package is `siliconnet`, the entry point is `python -m siliconnet`, user data lives in `~/Library/Application Support/SiliconNet`, and the data-directory override is `SILICONNET_DATA_DIR`.
- System proxy is managed with `networksetup` across every enabled network service, with the previous state backed up to `macos_proxy_state.json` and restored on exit.
- Single admin fallback: when `networksetup` is refused, the same command batch is replayed once through `osascript … with administrator privileges`.
- Autostart uses a user LaunchAgent (`~/Library/LaunchAgents/com.siliconnet.SiliconNetDPIBypass.plist`) loaded with `launchctl bootstrap`, falling back to `launchctl load -w` on older systems.
- Network diagnostics use an `lsof` based flow parser; the dashboard reports the managed network services.
- Menu bar item uses pystray's native macOS backend, confirmation dialogs use `osascript`, and the full shutdown flushes DNS with `dscacheutil -flushcache`.
- New logo. `assets/siliconnet_app.png` is the full mark; `assets/siliconnet_tray.png` is the artwork alone on a transparent plate.
- `status_bar.py` adapts pystray's icon to macOS conventions, each step falling back to pystray's own behavior if unavailable:
  - the status bar image is rebuilt at twice the point size and flagged as a template, so it is crisp on Retina and inverts on a dark menu bar;
  - the process takes the accessory activation policy, so a menu bar utility no longer holds a Dock tile or an app switcher entry;
  - a run loop timer rebuilds the menu every two seconds, so the status and ping lines are no longer frozen at the values they had at startup.
- Ships `SiliconNet.command` for Finder, `siliconnet-launcher.sh`, and the macOS build/verify release scripts.
- Removed every non-macOS remnant: registry-style autostart naming, the Windows-only `SIGBREAK` handler, UWP regression guards, and PyInstaller/installer artifacts from the packaging and ignore rules.

Carried over from the proxy core this release is built on: upstream connections use Happy Eyeballs (RFC 8305), racing IPv6 and IPv4 with a 250 ms stagger, so dual-stack sites no longer hang on networks that advertise but cannot route IPv6. Plain-HTTP passthrough is not DoH-resolved or blocked, so privacy mode applies to configured bypass sites only.
