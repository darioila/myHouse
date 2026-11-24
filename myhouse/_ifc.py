# SPDX-License-Identifier: GPL-3.0-or-later
"""Tag IFC sul sotto-gruppo che contiene la mesh (come wall_part in muri.py).

Il gruppo esterno non viene etichettato: l'esportazione IFC legge i gruppi
foglia con geometria. Va richiamato anche dopo ogni ricostruzione dei figli.
"""
from __future__ import annotations

from core import bim


def _leaves(g):
    kids = list(getattr(g, "children", None) or ())
    if not kids:
        yield g
        return
    for k in kids:
        yield from _leaves(k)


def tag(g, ifc_class, name=None):
    name = name or getattr(g, "name", "") or ""
    if getattr(g, "children", None) and getattr(g, "ifc", None):
        try:
            bim.untag_group(g)
        except Exception:
            pass
    for leaf in _leaves(g):
        if leaf is not g and getattr(leaf, "ifc", None):
            continue
        bim.tag_group(leaf, ifc_class, name)
