import { createMarkupSurfaceFacet } from "@hypit/hypit/markup";
import { canonicalize, sameType } from "@hypit/hypit/protocol";
import { sealGraphFragment } from "@hypit/hypit/author";
import { createAdmissionPackageFacet } from "@hypit/hypit/admission";
import { createProducerPackageFacet } from "@hypit/hypit/producer";
import { compositionTypes } from "@hypit/composition";
import { staticLayout } from "./layout.js";

const module = { name: "@hd-talking-head/hypit-native-layout", version: "1" };
const producer = { module, name: "layout" };
const inline = (record) => record?.value?.kind === "inline" ? record.value.value : (() => { throw new Error("Layout input must be inline."); })();
const value = (data) => ({ kind: "inline", value: canonicalize(data) });
const component = { producers: [{ producer, handler: ({ inputs }) => ({ outputs: { visual: value(staticLayout(inline(inputs.input), { semanticFamily: "plan_change_dialogue" })) }, needs: {} }) }] };
export const manifest = { format: "hypit.module@1", ...module, dependencies: [{ module: compositionTypes.visualTrack.module }], types: [], capabilities: [], producers: [{ name: "layout", inputs: [{ name: "input", type: compositionTypes.visualTrack }], outputs: [{ name: "visual", type: compositionTypes.visualTrack }], needs: [] }] };
const declaration = { name: "layout", tag: "Layout", mode: "structured", outputs: [compositionTypes.visualTrack], vocabulary: { summary: "Static portrait layout for a native chat VisualTrack.", attributes: [{ name: "id", kind: "literal", required: true, summary: "layout id" }, { name: "input", kind: "expression", required: true, summary: "input VisualTrack" }, { name: "semantic-family", kind: "literal", required: false, summary: "plan_change_dialogue" }], children: [], ports: [{ name: "visual", type: compositionTypes.visualTrack, summary: "scaled VisualTrack" }] } };
export const decodeSurface = ({ element, resolveReference }) => {
  const raw = element.attributes.input;
  if (!raw || raw.kind !== "reference") throw new Error("Layout input must be a reference.");
  const found = resolveReference(raw.path);
  if (!found || !sameType(found.type, compositionTypes.visualTrack)) throw new Error("Layout input must be a VisualTrack.");
  const id = String(element.attributes.id);
  const input = { name: "input", type: compositionTypes.visualTrack };
  const fragment = sealGraphFragment({ inputs: [input], operations: [{ id: "layout", producer, inputs: { input: { kind: "fragment-input", name: "input" } }, result: { kind: "output", name: "visual" } }], exports: [{ name: "visual", type: compositionTypes.visualTrack, root: { kind: "fragment-operation", operation: "layout" } }] });
  return { records: [], fragments: [fragment], components: [{ id, fragment: fragment.id, inputs: { input: found.ref }, outputs: { visual: `${id}.visual` }, range: element.range }], exports: [`${id}.visual`] };
};
export const hypitPackage = { format: "hypit.package@1", modules: [{ manifest }], facets: [createProducerPackageFacet(component), createAdmissionPackageFacet(component), createMarkupSurfaceFacet({ module, declaration, handler: decodeSurface })] };
export default hypitPackage;
