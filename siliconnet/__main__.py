"""Command-line entry point for SiliconNet on macOS."""

from __future__ import annotations

from .bootstrap import create_app


def main() -> None:
    app = create_app(__file__)
    app.start()


if __name__ == "__main__":
    main()
