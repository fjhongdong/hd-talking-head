// Browser line balancing may choose between words, never inside a word or keyword.
export const lineUnits = (text, emphasis = null) => {
  const ends = [...new Intl.Segmenter('zh', {granularity: 'word'}).segment(text)]
    .map(({index, segment}) => index + segment.length)
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
