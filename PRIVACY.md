# Privacy

SiliconNet runs locally. It does not send telemetry, analytics, crash reports, or update checks.

Runtime data is stored in `${SILICONNET_DATA_DIR}` or `~/Library/Application Support/SiliconNet`.

| File | Purpose |
|---|---|
| `config.json` | User configuration |
| `bypass.log` | Warning/error log |
| `macos_proxy_state.json` | Temporary backup of the previous proxy settings of each network service |
| `strategy_cache.json` | Learned strategy cache |
| `ai_strategy.json` | Adaptive strategy learning data |
| `stats.json` | Aggregate runtime counters |

When autostart is enabled, SiliconNet writes `~/Library/LaunchAgents/com.siliconnet.SiliconNetDPIBypass.plist` and its LaunchAgent output goes to `~/Library/Logs/SiliconNet/`. Disabling autostart removes the plist.

Network-flow diagnostics run `lsof` locally and the results stay on the machine. SiliconNet does not edit shell profile files.
