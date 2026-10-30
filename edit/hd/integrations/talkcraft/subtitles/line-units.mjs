// ICU words are not always reading units: e.g. "两 / 件 / 事" is one short phrase.
// Keep a quantity/classifier and its immediately following Chinese word together.
export const wordUnits = (text) => {
  const segments = [...new Intl.Segmenter('zh', {granularity: 'word'}).segment(text)];
  const protectedRanges = [];
  const quantities = /(?:第?[零〇一二两三四五六七八九十百千万亿几数]+|\d+(?:\.\d+)?|[这那每各某])[个件份项种次条张本位家台套步段页句笔名只块杯瓶幅篇场所座辆封首门类组批]/gu;
  const matches = [...text.matchAll(quantities)];
  for (const match of matches) {
    const prefixEnd = match.index + match[0].length;
    const containing = segments.find(({index, segment}) => index < prefixEnd && index + segment.length > prefixEnd);
    const next = segments.find(({index}) => index === prefixEnd);
    // Keep clear connectors/modifiers outside the quantity. This only declines
    // extra glue; ICU words remain intact, without trying to infer noun phrases.
    const continuation = next && (
      /^(?:又|再|也|都|还|就|才)/u.test(next.segment)
      || /^(?:很|太|更|最|挺|非常|比较|相当|特别)/u.test(next.segment)
      || matches.some((other) => other !== match && (
        other.index === prefixEnd || other.index + other[0].length === match.index
      ))
    );
    const end = containing ? containing.index + containing.segment.length
      : !continuation && next?.isWordLike && /^\p{Script=Han}+$/u.test(next.segment)
        ? next.index + next.segment.length : prefixEnd;
    protectedRanges.push({start: match.index, end});
  }
  let start = 0;
  return segments.map(({index, segment}) => index + segment.length)
    .filter((end) => !protectedRanges.some((range) => end > range.start && end < range.end))
    .map((end) => {
      const unit = {start, end};
      start = end;
      return unit;
    });
};

// Browser balancing uses the same reading units as cue partitioning.
export const lineUnits = (text, emphasis = null) => {
  const ends = wordUnits(text).map(({end}) => end)
    .filter((end) => end === text.length || (
      !(emphasis && end > emphasis.text_start && end < emphasis.text_end)
      && !/[\p{Ps}\p{Pi}]$/u.test(text.slice(0, end))
      && !/^[\p{Pe}\p{Pf}、。，．！？：；,.!?:;…]/u.test(text.slice(end))
    ));
  let start = 0;
  return ends.map((end) => {
    const unit = {start, end};
    start = end;
    return unit;
  });
};
