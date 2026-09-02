import io
import sys
import types
import unittest
from unittest.mock import patch

try:
    from PIL import Image
except ImportError:
    Image = None

from siliconnet.status_bar import MENU_REFRESH_INTERVAL, RETINA_SCALE, status_bar_icon_class

ACCESSORY_POLICY = 1
MENU_BAR_THICKNESS = 22


class _FakeNSImage:
    def __init__(self, data):
        self.data = data
        self.size = None
        self.template = None

    def setSize_(self, size):
        self.size = size

    def setTemplate_(self, value):
        self.template = value


class _FakeNSImageFactory:
    """Stands in for ``NSImage.alloc().initWithData_(...)``."""

    def __init__(self):
        self.created = []

    def alloc(self):
        return self

    def initWithData_(self, data):
        image = _FakeNSImage(data)
        self.created.append(image)
        return image


class _FakeButton:
    def __init__(self):
        self.images = []

    def setImage_(self, image):
        self.images.append(image)


class _FakeStatusItem:
    def __init__(self):
        self._button = _FakeButton()

    def button(self):
        return self._button


class _FakeStatusBar:
    def thickness(self):
        return MENU_BAR_THICKNESS


class _FakeApp:
    def __init__(self):
        self.policies = []

    def setActivationPolicy_(self, policy):
        self.policies.append(policy)


class _FakeTimer:
    def __init__(self):
        self.scheduled = []

    def scheduledTimerWithTimeInterval_repeats_block_(self, interval, repeats, block):
        self.scheduled.append((interval, repeats, block))
        return f"timer-{len(self.scheduled)}"


class _FakePystrayIcon:
    """The pystray internals the macOS backend exposes to a subclass."""

    def __init__(self, image):
        self._icon = image
        self._icon_image = None
        self._status_bar = _FakeStatusBar()
        self._status_item = _FakeStatusItem()
        self._app = _FakeApp()
        self.asserted = 0
        self.ran = 0
        self.menu_updates = 0

    def _assert_image(self):
        self.asserted += 1
        self._icon_image = _FakeNSImage(b"pystray-bitmap")

    def _run(self):
        self.ran += 1

    def update_menu(self):
        self.menu_updates += 1


def _pystray(icon_class=_FakePystrayIcon):
    return types.SimpleNamespace(Icon=icon_class)


def _source_image(size=(128, 96)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((0, 0, 0, 255), (10, 10, size[0] - 10, size[1] - 10))
    return image


def _cocoa_modules(image_factory, timer=None):
    appkit = types.SimpleNamespace(
        NSImage=image_factory,
        NSApplicationActivationPolicyAccessory=ACCESSORY_POLICY,
    )
    foundation = types.SimpleNamespace(
        NSData=lambda payload: payload,
        NSTimer=timer or _FakeTimer(),
    )
    return {"AppKit": appkit, "Foundation": foundation}


@unittest.skipUnless(Image is not None, "Pillow is required for menu bar icon checks")
class MenuBarImageTests(unittest.TestCase):
    def _icon(self, modules, image=None):
        icon = status_bar_icon_class(_pystray()).__call__(image or _source_image())
        with patch.dict(sys.modules, modules):
            icon._assert_image()
        return icon

    def test_image_is_rebuilt_at_retina_scale_and_marked_as_a_template(self):
        factory = _FakeNSImageFactory()
        icon = self._icon(_cocoa_modules(factory))

        self.assertEqual(len(factory.created), 1)
        image = factory.created[0]
        self.assertIs(icon._icon_image, image)
        self.assertEqual(image.size, (MENU_BAR_THICKNESS, MENU_BAR_THICKNESS))
        self.assertTrue(image.template)
        self.assertEqual(icon._status_item.button().images, [image])

    def test_rebuilt_bitmap_is_square_and_twice_the_point_size(self):
        factory = _FakeNSImageFactory()
        self._icon(_cocoa_modules(factory))

        with Image.open(io.BytesIO(factory.created[0].data)) as bitmap:
            self.assertEqual(
                bitmap.size,
                (MENU_BAR_THICKNESS * RETINA_SCALE, MENU_BAR_THICKNESS * RETINA_SCALE),
            )

    def test_wide_artwork_keeps_its_aspect_ratio_and_is_centered(self):
        factory = _FakeNSImageFactory()
        self._icon(_cocoa_modules(factory), image=_source_image((200, 100)))

        with Image.open(io.BytesIO(factory.created[0].data)) as bitmap:
            rgba = bitmap.convert("RGBA")
        left, top, right, bottom = rgba.getbbox()
        self.assertGreater(right - left, bottom - top)
        self.assertAlmostEqual(left, rgba.width - right, delta=1)
        self.assertAlmostEqual(top, rgba.height - bottom, delta=1)

    def test_missing_cocoa_falls_back_to_marking_pystrays_bitmap(self):
        icon = self._icon({"AppKit": None})

        self.assertEqual(icon.asserted, 1)
        self.assertTrue(icon._icon_image.template)
        self.assertEqual(icon._status_item.button().images, [icon._icon_image])

    def test_fallback_tolerates_a_missing_bitmap(self):
        class _NoImage(_FakePystrayIcon):
            def _assert_image(self):
                self._icon_image = None

        icon = status_bar_icon_class(_pystray(_NoImage))(_source_image())
        with patch.dict(sys.modules, {"AppKit": None}):
            icon._assert_image()

        self.assertIsNone(icon._icon_image)
        self.assertEqual(icon._status_item.button().images, [])

    def test_fallback_tolerates_an_unsupported_selector(self):
        class _Unsupported(_FakePystrayIcon):
            def _assert_image(self):
                image = _FakeNSImage(b"x")
                image.setTemplate_ = self._refuse
                self._icon_image = image

            @staticmethod
            def _refuse(_value):
                raise AttributeError("setTemplate_ is unavailable")

        icon = status_bar_icon_class(_pystray(_Unsupported))(_source_image())
        with patch.dict(sys.modules, {"AppKit": None}):
            icon._assert_image()

        self.assertEqual(icon._status_item.button().images, [])


@unittest.skipUnless(Image is not None, "Pillow is required for menu bar icon checks")
class RunTests(unittest.TestCase):
    def test_run_drops_the_dock_tile_and_starts_the_menu_refresh(self):
        timer = _FakeTimer()
        icon = status_bar_icon_class(_pystray())(_source_image())

        with patch.dict(sys.modules, _cocoa_modules(_FakeNSImageFactory(), timer)):
            icon._run()

        self.assertEqual(icon._app.policies, [ACCESSORY_POLICY])
        self.assertEqual(len(timer.scheduled), 1)
        interval, repeats, _block = timer.scheduled[0]
        self.assertEqual(interval, MENU_REFRESH_INTERVAL)
        self.assertTrue(repeats)
        self.assertEqual(icon.ran, 1)

    def test_scheduled_block_rebuilds_the_menu(self):
        timer = _FakeTimer()
        icon = status_bar_icon_class(_pystray())(_source_image())

        with patch.dict(sys.modules, _cocoa_modules(_FakeNSImageFactory(), timer)):
            icon._run()
        timer.scheduled[0][2](None)
        timer.scheduled[0][2](None)

        self.assertEqual(icon.menu_updates, 2)

    def test_a_failing_menu_rebuild_does_not_escape_the_timer(self):
        class _Broken(_FakePystrayIcon):
            def update_menu(self):
                raise RuntimeError("menu is gone")

        timer = _FakeTimer()
        icon = status_bar_icon_class(_pystray(_Broken))(_source_image())

        with patch.dict(sys.modules, _cocoa_modules(_FakeNSImageFactory(), timer)):
            icon._run()
        timer.scheduled[0][2](None)

    def test_run_still_starts_without_cocoa(self):
        icon = status_bar_icon_class(_pystray())(_source_image())

        with patch.dict(sys.modules, {"AppKit": None, "Foundation": None}):
            icon._run()

        self.assertEqual(icon._app.policies, [])
        self.assertIsNone(icon._menu_refresh_timer)
        self.assertEqual(icon.ran, 1)


if __name__ == "__main__":
    unittest.main()
