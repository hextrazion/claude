"""Writes packaging/icon.ico from the same drawing the tray icon uses."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app" / "backend"))

from studio.desktop import make_icon_image  # noqa: E402

make_icon_image(256).save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", HERE / "icon.ico")
