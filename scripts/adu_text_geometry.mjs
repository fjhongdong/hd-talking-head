// Runs in the actual native iframe after its fonts and static host styles settle.
export function validateAduTextGeometry(frame) {
  const doc = frame.contentDocument;
  const win = frame.contentWindow;
  const context = doc.createElement('canvas').getContext('2d');
  const frameRect = frame.getBoundingClientRect();
  const frameX = frameRect.width / frame.offsetWidth;
  const frameY = frameRect.height / frame.offsetHeight;
  const originX = frameRect.left + frame.clientLeft * frameX;
  const originY = frameRect.top + frame.clientTop * frameY;
  const fail = (message, detail) => {
    throw new Error('Adu actual text geometry: ' + message + ' ' + JSON.stringify(detail));
  };
  const mapRect = box => ({left: originX + box.left * frameX,
    right: originX + box.right * frameX, top: originY + box.top * frameY,
    bottom: originY + box.bottom * frameY});
  if (!context || ![frameX, frameY].every(value => Number.isFinite(value) && value > 0)) {
    fail('unavailable frame geometry', {});
  }
  const cards = [...doc.querySelectorAll('.card')];
  if (cards.length !== 2) fail('expected the two native comparison cards', {count: cards.length});
  const boxes = [];
  for (const [cardIndex, card] of cards.entries()) {
    const cardRect = card.getBoundingClientRect();
    const scaleX = cardRect.width / card.offsetWidth;
    const scaleY = cardRect.height / card.offsetHeight;
    for (let node = card; node; node = node.parentElement) {
      const transform = win.getComputedStyle(node).transform;
      if (transform !== 'none') {
        const matrix = new win.DOMMatrixReadOnly(transform);
        if (!matrix.is2D || Math.abs(matrix.b) > 1e-6 || Math.abs(matrix.c) > 1e-6) {
          fail('unsupported rotated text layout', {card: cardIndex});
        }
      }
    }
    const lines = [...card.querySelectorAll(':scope > div:nth-child(n+2)')];
    for (const [lineIndex, line] of lines.entries()) {
      const text = line.textContent;
      const style = win.getComputedStyle(line);
      if (line.children.length) fail('mixed text layout', {text});
      const range = doc.createRange();
      range.selectNodeContents(line);
      const rects = [...range.getClientRects()].filter(rect => rect.width && rect.height);
      if (rects.length !== 1) fail('unhandled wrapping', {text, lines: rects.length});
      context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      context.fontKerning = style.fontKerning;
      context.letterSpacing = style.letterSpacing;
      context.wordSpacing = style.wordSpacing;
      const metrics = context.measureText(text);
      const values = [metrics.actualBoundingBoxLeft, metrics.actualBoundingBoxRight,
        metrics.actualBoundingBoxAscent, metrics.actualBoundingBoxDescent];
      if (!values.every(Number.isFinite) || values[2] + values[3] <= 0) {
        fail('missing actual glyph metrics', {text});
      }
      const before = line.getBoundingClientRect();
      const marker = doc.createElement('span');
      marker.style.cssText = 'display:inline-block;width:0;height:0;padding:0;margin:0;border:0;vertical-align:baseline';
      let baseline;
      try {
        line.appendChild(marker);
        baseline = marker.getBoundingClientRect().top;
        const during = line.getBoundingClientRect();
        if (Math.abs(before.width - during.width) > 0.01 || Math.abs(before.height - during.height) > 0.01) {
          fail('baseline measurement changed layout', {text});
        }
      } finally {
        marker.remove();
      }
      const ink = mapRect({left: rects[0].left - values[0] * scaleX,
        right: rects[0].left + values[1] * scaleX,
        top: baseline - values[2] * scaleY, bottom: baseline + values[3] * scaleY});
      const box = {...ink, text, card: cardIndex, kind: lineIndex ? 'body' : 'title', row: lineIndex};
      const container = mapRect(cardRect);
      if (box.left < container.left || box.right > container.right ||
          box.top < container.top || box.bottom > container.bottom) fail('glyphs outside card', box);
      for (const previous of boxes.filter(item => item.card === cardIndex)) {
        if (box.left < previous.right && previous.left < box.right &&
            box.top < previous.bottom && previous.top < box.bottom) {
          fail('overlapping glyphs', {first: previous, second: box});
        }
      }
      boxes.push(box);
    }
  }
  return {coordinate_space: 'final_canvas', boxes};
}
