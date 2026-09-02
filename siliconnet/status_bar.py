"""macOS menu bar presentation for the pystray status item.

pystray treats a macOS status item like a Windows tray icon: it hands AppKit a
bitmap sized to the menu bar in points, leaves the process holding a Dock tile,
and builds the menu once at startup. A menu bar utility is expected to do none
of those, so this module adapts the icon class before it is instantiated.

Every adaptation is optional. If AppKit is missing or a selector is unavailable,
the icon falls back to what pystray would have done on its own.
"""

from __future__ import annotations

import io

# Rebuilding the menu is what re-evaluates the status and ping labels, which are
# callables. pystray builds the menu once, so nothing refreshes them otherwise.
MENU_REFRESH_INTERVAL = 2.0

# Menu bar bitmaps are supplied at twice the point size so Retina stays sharp.
RETINA_SCALE = 2


def status_bar_icon_class(pystray_module):
    """Return a pystray Icon subclass that behaves like a macOS menu bar app."""

    class StatusBarIcon(pystray_module.Icon):
        def _assert_image(self) -> None:
            super()._assert_image()
            self._apply_menu_bar_image()

        def _apply_menu_bar_image(self) -> None:
            """Replace pystray's bitmap with a 2x template image.

            pystray downsamples the icon to the menu bar thickness in pixels,
            which a Retina display then has to stretch back up. Supplying twice
            the pixels and declaring the smaller point size keeps it crisp, and
            the template flag lets macOS invert it on a dark menu bar.
            """
            try:
                # macOS-only imports, kept local so the module loads anywhere.
                import AppKit
                import Foundation
                from PIL import Image

                thickness = int(self._status_bar.thickness())
                pixels = thickness * RETINA_SCALE
                glyph = self._icon.convert("RGBA")
                glyph.thumbnail((pixels, pixels), Image.Resampling.LANCZOS)

                canvas = Image.new("RGBA", (pixels, pixels), (0, 0, 0, 0))
                canvas.alpha_composite(
                    glyph,
                    ((pixels - glyph.width) // 2, (pixels - glyph.height) // 2),
                )
                buffer = io.BytesIO()
                canvas.save(buffer, "PNG")

                image = AppKit.NSImage.alloc().initWithData_(
                    Foundation.NSData(buffer.getvalue())
                )
                image.setSize_((thickness, thickness))
                image.setTemplate_(True)
                self._icon_image = image
                self._status_item.button().setImage_(image)
            except Exception:
                self._mark_template()

        def _mark_template(self) -> None:
            """Fallback: at least let macOS invert whatever pystray produced."""
            image = getattr(self, "_icon_image", None)
            if image is None:
                return
            try:
                image.setTemplate_(True)
                self._status_item.button().setImage_(image)
            except Exception:
                pass

        def _use_accessory_activation_policy(self) -> None:
            """Drop the Dock tile; a menu bar utility is an accessory app."""
            try:
                import AppKit

                self._app.setActivationPolicy_(
                    AppKit.NSApplicationActivationPolicyAccessory
                )
            except Exception:
                pass

        def _schedule_menu_refresh(self) -> None:
            """Rebuild the menu on the main run loop so its labels stay current.

            AppKit may only be touched from the main thread, so this is a timer
            on the run loop rather than a worker thread.
            """
            def refresh(_timer):
                try:
                    self.update_menu()
                except Exception:
                    pass

            try:
                import Foundation

                self._menu_refresh_timer = (
                    Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
                        MENU_REFRESH_INTERVAL, True, refresh
                    )
                )
            except Exception:
                self._menu_refresh_timer = None

        def _run(self) -> None:
            self._use_accessory_activation_policy()
            self._schedule_menu_refresh()
            super()._run()

    return StatusBarIcon
