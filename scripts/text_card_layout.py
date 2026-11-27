"""Bind shared intrinsic card styling to a locally authored HTML scene."""
from __future__ import annotations

from pathlib import Path
import re

from package_paths import PACKAGE_ROOT


CARD_CSS = PACKAGE_ROOT / "assets/text-card-layout/card.css"


def card_rules(container, content):
    return re.sub(
        r"\.hd-text-card(?:-content)?(?=\s*\{)",
        lambda rule: content if rule[0].endswith("-content") else container,
        CARD_CSS.read_text(encoding="utf-8"),
    )


def _local_entry(directory, entry):
    root = Path(directory).resolve(strict=True)
    path = root / entry
    if path.resolve(strict=True) != path or not path.is_relative_to(root):
        raise ValueError("Text card layout requires a local authored entry")
    return path


def install_card_css(directory, entry):
    path = _local_entry(directory, entry)
    page = path.read_text(encoding="utf-8")
    if "hd-text-card" not in page:
        return
    if '<style id="hd-text-card-layout">' in page:
        return
    head_end = re.search(r"</head\s*>", page, re.I)
    if not head_end or path.stat().st_nlink != 1:
        raise ValueError("Text card styling requires a regular authored page with a head element")
    css = CARD_CSS.read_text(encoding="utf-8")
    block = f'<style id="hd-text-card-layout">\n{css}</style>\n'
    path.write_text(page[:head_end.start()] + block + page[head_end.start():], encoding="utf-8")


def install_react_card_css(directory, entry):
    path = _local_entry(directory, entry)
    source = path.read_text(encoding="utf-8")
    if "hd-text-card" not in source:
        return
    css_path = path.with_name("hd-text-card-layout.css")
    css = CARD_CSS.read_bytes()
    if path.stat().st_nlink != 1 or css_path.is_symlink():
        raise ValueError("Text card layout requires regular local authored files")
    if css_path.exists():
        if css_path.read_bytes() != css:
            raise ValueError("Authored scene already uses a different card stylesheet")
    else:
        with css_path.open("xb") as stylesheet:
            stylesheet.write(css)
    style_import = 'import "./hd-text-card-layout.css";'
    if style_import not in source:
        path.write_text(style_import + "\n" + source, encoding="utf-8")
