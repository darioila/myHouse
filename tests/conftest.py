"""Headless checks for the myHouse plugin against the IngeTrazo source tree.

Run:  QT_QPA_PLATFORM=offscreen <ingetrazo venv>/bin/pytest tests
The host source is found through INGETRAZO_SRC (default: ../../ingetrazo).
"""
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOST_SRC = os.environ.get("INGETRAZO_SRC", os.path.abspath(os.path.join(ROOT, "..", "..", "ingetrazo")))

for path in (ROOT, HOST_SRC):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MYHOUSE_LANG", "en")
# Keep the developer's installed extensions, library and settings out of the run.
_data = tempfile.mkdtemp(prefix="myhouse-tests-")
os.environ["XDG_DATA_HOME"] = _data
os.environ["INGETRAZO_USER_LIBRARY"] = os.path.join(_data, "my-library")
os.environ.setdefault("INGETRAZO_CATEGORIES_DB", os.path.join(_data, "categories.sqlite"))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])
QSettings.setDefaultFormat(QSettings.IniFormat)
for _scope in (QSettings.UserScope, QSettings.SystemScope):
    QSettings.setPath(QSettings.IniFormat, _scope, _data)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def myhouse():
    import importlib
    return importlib.import_module("myhouse")


_WIN = []


def _window():
    """The one IngeTrazo main window of the run, with myHouse set up in it."""
    if not _WIN:
        import myhouse
        from views.extension_api import ExtensionApp
        from views.main_window import MainWindow
        win = MainWindow()
        myhouse.setup(ExtensionApp(win, "myhouse"))
        _WIN.append(win)
    return _WIN[0]


@pytest.fixture(scope="session")
def window(myhouse):
    return _window()


@pytest.fixture
def viewport(window):
    """The window's viewport on an empty scene."""
    vp = window.viewport
    scene = vp.scene
    for g in list(scene.groups):
        scene.groups.remove(g)
    scene.selection.clear() if hasattr(scene.selection, "clear") else None
    return vp
