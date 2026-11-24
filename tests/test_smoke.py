import importlib
import pkgutil

from PySide6.QtWidgets import QToolBar


def test_every_module_imports(myhouse):
    for info in pkgutil.iter_modules(myhouse.__path__):
        importlib.import_module(f"myhouse.{info.name}")


def test_setup_registers_every_feature(myhouse, window):
    bar = window.findChild(QToolBar, "myhouse_toolbar")
    assert bar is not None
    texts = {a.text() for m in window.menuBar().findChildren(type(window.menuBar().addMenu("x"))) for a in m.actions()}
    assert "Walls" in texts and "Door" in texts and "Window" in texts and "Roof" in texts
    assert not [t for t in texts if t.startswith("⚠")], "a feature failed to load"
