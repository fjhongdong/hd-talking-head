"""Use measured text dimensions in Sweety's bundled web recipes."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from package_paths import PACKAGE_ROOT


def _replace(source, original, layout):
    if source.count(original) != 1:
        raise ValueError("Sweety card source differs from its registered version")
    return source.replace(original, layout, 1)


def _callout(source):
    source = _replace(source, "    const w = ctx.width - 2 * pad, h = ctx.height - 2 * pad - (p.tail ? 30 : 0);", """    const fontSize = p.size || 54, inset = 0.4 * fontSize;
    const text = p.text || "", options = {fontFamily: family(p.font || "hand"), fontSize, lineHeight: 1.2};
    const measure = window.HdTextCard.measureTextCard;
    const natural = measure(text, options);
    const w = Math.min(ctx.width - 2 * pad, Math.max(2 * inset + natural.width, fontSize * 2));
    const h = Math.max(fontSize, measure(text, {...options, width: w - 2 * inset}).height) + 2 * inset;
    const fullHeight = h + (p.tail ? 30 : 0);
    if (fullHeight + 2 * pad > ctx.height) throw new Error("Callout text needs a taller space");
    const left = (ctx.width - w) / 2, top = (ctx.height - fullHeight) / 2;""")
    for original, layout in (
        ("rough.svg(layer).rectangle(pad, pad, w, h, o)", "rough.svg(layer).rectangle(left, top, w, h, o)"),
        ("const x = tail.endsWith('right') ? pad + w * 0.75 : pad + w * 0.2;",
         "const x = left + w * (tail.endsWith('right') ? 0.75 : 0.2);"),
        ("[[x, pad + h - 2], [x + 34, pad + h - 2], [x - 6, pad + h + 30]]",
         "[[x, top + h - 2], [x + 34, top + h - 2], [x - 6, top + h + 30]]"),
        ("left: `${pad}px`, top: `${pad}px`, width: `${w}px`, height: `${h}px`, display: 'flex'",
         "left: `${left}px`, top: `${top}px`, width: `${w}px`, height: `${h}px`, display: 'flex'"),
        ("    const words = document.createElement('div');   // the flex item whose lines wrap between words\n"
         "    words.style.minWidth = '0';\n    label.appendChild(words);\n    root.appendChild(label);\n"
         "    setWords(words, p.text || '', w - 0.8 * (p.size || 54));\n"
         "    root.style.transformOrigin = tail.endsWith('right') ? '75% 100%' : '20% 100%';",
         """    label.appendChild(window.HdTextCard.textCardContent(text, {...options, width: w - 2 * inset}));
    root.appendChild(label);
    root.style.transformOrigin = `${left + w * (tail.endsWith('right') ? 0.75 : 0.2)}px ${top + fullHeight}px`;"""),
    ):
        source = _replace(source, original, layout)
    return source


def _cards(source):
    source = _replace(source,
        "    const w = Math.min(cw * 0.8, ch * 1.25), h = Math.min(ch * 0.78, w * 0.78), bar = p.bar || accentOf(p);",
        """    const w = Math.min(cw * 0.8, ch * 1.25), baseHeight = Math.min(ch * 0.78, w * 0.78);
    const text = {width: w * 0.84, fontFamily: family(p.font || 'hand'),
                  fontSize: Math.min(baseHeight * 0.3, 34), color: ink(p)};
    const labels = (p.labels || []).slice(0, count), bar = p.bar || accentOf(p);
    const body = labels.map(label => window.HdTextCard.measureTextCard(label, text).height);
    const h = Math.max(baseHeight, (Math.max(0, ...body) + text.fontSize) / 0.8);
    if (h > ch * 0.9) throw new Error("Card text needs more space between rows");""")
    source = _replace(source,
        "      [0.42, 0.6, 0.78].forEach((f, k) => g.appendChild(pen.line",
        "      if (!labels[i]) [0.42, 0.6, 0.78].forEach((f, k) => g.appendChild(pen.line")
    return _replace(source,
        "      if (p.labels && p.labels[i]) appear(wrapWide(label(root, p.labels[i], cx, cy + h * 0.12, Math.min(h * 0.3, 34), p), w * 0.9, 'center'), start + i * (p.card_ms || 60) + 150);",
        """      if (labels[i]) {
        const content = document.createElementNS(NS, 'foreignObject');
        content.setAttribute('x', cx - text.width / 2);
        content.setAttribute('y', cy + h * 0.1 - body[i] / 2);
        content.setAttribute('width', text.width);
        content.setAttribute('height', body[i] + text.fontSize * 0.35 + 1);
        const words = window.HdTextCard.textCardContent(labels[i], text);
        words.style.transform = 'translateY(0px)';
        content.appendChild(words);
        g.appendChild(content);
        appear(words, start + i * (p.card_ms || 60) + 150);
      }""")


def _flow(source):
    source = _replace(source,
        "      const cx = u * W, cy = v * H, w = sw * W, h = sh * H, at = node.ms ?? start + i * (p.stagger || 260), shape = node.shape || 'round';",
        """      const cx = u * W, cy = v * H, w = sw * W;
      const at = node.ms ?? start + i * (p.stagger || 260), shape = node.shape || 'round';
      const boxed = shape === 'round' || shape === 'box';
      const fontSize = node.text_size || size, textWidth = w - 12;
      const options = {width: textWidth, fontFamily: family(p.font || 'hand'), fontSize,
                       color: node.text_color || ink(p)};
      const h = boxed && node.text
        ? Math.max(sh * H, window.HdTextCard.measureTextCard(node.text, options).height + fontSize * 0.6)
        : sh * H;
      if (boxed && h > 2 * Math.min(cy, H - cy)) throw new Error("Flow card text needs a taller node space");""")
    return _replace(source,
        "      const text = block(root, node.text || '', cx - w / 2 + 6, cy, w - 12, node.text_size || size, p, node.text_color || (shape === 'none' ? color : ink(p)));",
        """      const text = boxed ? window.HdTextCard.textCardContent(node.text || '', options)
                         : block(root, node.text || '', cx - w / 2 + 6, cy, w - 12, fontSize, p, node.text_color || (shape === 'none' ? color : ink(p)));
      if (boxed) {
        Object.assign(text.style, {position: 'absolute', left: `${cx - textWidth / 2}px`,
                                    top: `${cy}px`, transform: 'translateY(-50%)'});
        root.appendChild(text);
      }""")


@contextmanager
def sizing_assets(web_motion, recipe, shared=PACKAGE_ROOT / 'assets/text-card-layout'):
    """Supply a private asset directory to the original renderer and cache key."""
    if recipe not in {'cards', 'callout', 'flow'}:
        yield
        return
    original = web_motion.ASSETS
    source = (original / 'recipes.js').read_text(encoding='utf-8')
    if recipe == 'cards':
        source = _cards(source)
    elif recipe == 'callout':
        source = _callout(source)
    elif recipe == 'flow':
        source = _flow(source)
    measure = (shared / 'measure.js').read_text(encoding='utf-8')
    with TemporaryDirectory(prefix='sweety-text-cards-') as directory:
        private = Path(directory)
        (private / 'recipes.js').write_text(measure + '\n' + source, encoding='utf-8')
        for name in ('shim.js', 'vendor'):
            (private / name).symlink_to(original / name)
        try:
            web_motion.ASSETS = private
            yield
        finally:
            web_motion.ASSETS = original
