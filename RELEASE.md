# macOS Release

Build:

```bash
scripts/build_macos_release.sh
```

Verify:

```bash
scripts/verify_macos_release.sh
```

Expected outputs:

- `dist/siliconnet-macos-<version>.tar.gz`
- `dist/SHA256SUMS.txt`

Release archives must not contain `.venv`, `build`, cached bytecode, runtime logs/state, or macOS metadata (`._*`, `.DS_Store`).

The archive is unsigned, so document the quarantine step for users who download it with a browser:

```bash
xattr -dr com.apple.quarantine siliconnet-macos-<version>
```
