(function () {
  // Measure with the same browser line-breaking and font styles used for drawing.
  function textCardContent(text, {width, fontFamily, fontSize, lineHeight = 1.15, color}) {
    const element = document.createElement("div");
    element.className = "hd-text-card-content";
    element.textContent = text;
    Object.assign(element.style, {
      width: width === undefined ? "max-content" : `${width}px`,
      fontFamily, fontSize: `${fontSize}px`, lineHeight, color,
      whiteSpace: "pre-wrap", overflowWrap: "anywhere", textAlign: "center",
    });
    return element;
  }

  function measureTextCard(text, options) {
    const element = textCardContent(text, options);
    Object.assign(element.style, {position: "absolute", visibility: "hidden"});
    document.body.appendChild(element);
    const {width, height} = element.getBoundingClientRect();
    element.remove();
    return {width: Math.ceil(width), height: Math.ceil(height)};
  }

  window.HdTextCard = {textCardContent, measureTextCard};
})();
