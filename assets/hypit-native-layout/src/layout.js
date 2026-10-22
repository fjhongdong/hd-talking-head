/**
 * Static portrait layout for the native chat VisualTrack.
 * The input track is treated as immutable: only the root HTML program gets
 * layout declarations; its HTML, CSS, data and frame setup remain untouched.
 */
import { sealVisualTrack } from "@hypit/composition";

const style = (name, value) => ({ name, value });

export function staticLayout(track, options = {}) {
  if (!track || track.kind !== "visual" || track.visualIr !== "hypit.visual-ir@1") {
    throw new TypeError("staticLayout expects a sealed Hypit VisualTrack");
  }
  if (options.semanticFamily !== undefined && options.semanticFamily !== "plan_change_dialogue") {
    throw new Error("hypit-native-layout only accepts plan_change_dialogue");
  }
  const presents = track.presents.map((present) => ({
    ...present,
    elements: present.elements.map((element) => {
      if (element.kind !== "program" || element.parent !== undefined) return element;
      const existing = new Map((element.style ?? []).map((entry) => [entry.name, entry]));
      for (const declaration of [
        style("position", "absolute"),
        style("left", "0px"),
        style("top", "80px"),
        style("transform", "scale(2)"),
        style("transform-origin", "top left"),
      ]) existing.set(declaration.name, declaration);
      return { ...element, style: [...existing.values()] };
    }),
  }));
  return sealVisualTrack({ ...track, presents });
}

export const STATIC_LAYOUT = Object.freeze({
  semanticFamily: "plan_change_dialogue",
  logicalFrame: { width: 540, height: 480 },
  canvas: { width: 1080, height: 1920 },
  fps: 24,
  durationSeconds: { min: 5, max: 10 },
  layout: { scale: 2, origin: "top left", left: 0, top: 80 },
});
