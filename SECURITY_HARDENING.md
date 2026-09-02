# Security Hardening Notes

- Keep proxy changes user-scoped; the `osascript … with administrator privileges` replay must stay limited to the `networksetup` batch and must never be used to install anything.
- Preserve proxy backup/restore behavior whenever backend code changes.
- Keep autostart as a user LaunchAgent; do not add a `LaunchDaemon` or any `/Library` write.
- Keep release archives free of runtime state, virtual environments, bytecode, generated build output, and macOS metadata (`._*`, `.DS_Store`).
- Run `scripts/verify_macos_release.sh` before publishing.
