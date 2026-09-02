# Security

SiliconNet macOS is a local-only user-space proxy.

It does not:

- install kernel extensions or system daemons;
- install certificates;
- decrypt HTTPS traffic;
- run as root for normal use;
- write outside the user's home directory.

It writes the HTTP/HTTPS proxy settings of your enabled network services through `networksetup`. Before changing them, it stores a temporary backup in `macos_proxy_state.json` under the SiliconNet data directory and restores that state when SiliconNet stops normally.

If macOS refuses the change because the account is not an administrator, the same batch of `networksetup` commands is replayed once through `osascript … with administrator privileges`. That is the only elevated action in the application, it is limited to the proxy commands shown in the system prompt, and cancelling the prompt aborts the change.

Autostart is a user-level LaunchAgent in `~/Library/LaunchAgents`. No item is installed into `/Library/LaunchDaemons`.

Run verification before release:

```bash
scripts/verify_macos_release.sh
```
