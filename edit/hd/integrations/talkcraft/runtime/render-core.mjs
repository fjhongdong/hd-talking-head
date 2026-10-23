import {createHash} from "node:crypto";
import {mkdir, mkdtemp, readFile, rm, stat, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import path from "node:path";
import {bundle} from "@remotion/bundler";
import {renderMedia, selectComposition} from "@remotion/renderer";
import {resolveProductionCard} from "./card-dispatch.mjs";

const VERSION = "0.9.0";
const MODES = new Set(["text", "data", "annotation", "transition"]);
const ALLOWED_ARGUMENTS = new Set([
  "probe-mechanism", "probe-foundation", "probe-scene", "probe-text-layout", "probe-time-domain", "probe-determinism", "probe-card", "case", "sample-order", "frames", "alpha", "output", "browser", "title",
  "value", "runtime-root", "brief", "node", "playwright", "ffmpeg", "ffprobe",
  "runtime-contracts", "media-manifest",
]);

const parseArgs = (argv) => {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) throw new Error("invalid arguments");
    const name = key.slice(2);
    if (!ALLOWED_ARGUMENTS.has(name) || Object.hasOwn(result, name)) {
      throw new Error(`invalid or duplicate argument: ${key}`);
    }
    result[name] = value;
  }
  return result;
};

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const CARD_ID = /^[a-z][a-z0-9-]{0,63}$/;
const HASH = /^[0-9a-f]{64}$/;
const MEDIA_FD = /^\/dev\/fd\/[0-9]+$/;
const MEDIA_EXTENSION = new Set([".jpeg", ".jpg", ".mov", ".mp4", ".png", ".webm", ".webp"]);
const TRUSTED_ALPHA_GEOMETRY = new Map([
  ["02fd74fcaf4bd5e945b64a8d7d9dd67549351fbe00d3f30f54fcc09d2505b0af", {
    method: "libvpx-vp9-alpha-bbox-v1", width: 540, height: 600,
    sourceAlphaBBox: {x: 66, y: 25, width: 414, height: 575},
  }],
]);

const loadFoundationContract = async (runtimeRoot) => {
  const contract = JSON.parse(await readFile(path.join(runtimeRoot, "foundation-contract.json"), "utf8"));
  const unique = (values, count) => Array.isArray(values) && values.length === count &&
    values.every((value) => typeof value === "string" && value.length > 0) &&
    new Set(values).size === count;
  if (
    contract.schema_version !== "talkcraft-visual-foundations/v1" ||
    !unique(contract.backdrops, 12) || !unique(contract.frames, 8) ||
    JSON.stringify(contract.source_frames) !== JSON.stringify([0, 24, 48])
  ) {
    throw new Error("foundation contract is invalid");
  }
  return contract;
};

const loadSceneContract = async (runtimeRoot) => {
  const contract = JSON.parse(await readFile(path.join(runtimeRoot, "scene-foundation-contract.json"), "utf8"));
  const tokenKeys = ["accent", "canvas", "canvas_alt", "hairline", "ink", "ink_muted", "marker", "negative", "positive"];
  if (
    contract.schema_version !== "talkcraft-scene-foundation/v1" ||
    JSON.stringify(contract.plane_order) !== JSON.stringify(["background.screen", "background.world", "subject.world", "text.screen"]) ||
    JSON.stringify(contract.probe?.variants) !== JSON.stringify(["light-push", "dark-pull"]) ||
    JSON.stringify(contract.probe?.source_frames) !== JSON.stringify([0, 36, 71]) ||
    Object.keys(contract.themes?.light ?? {}).sort().join(",") !== tokenKeys.join(",") ||
    Object.keys(contract.themes?.dark ?? {}).sort().join(",") !== tokenKeys.join(",")
  ) {
    throw new Error("scene foundation contract is invalid");
  }
  return contract;
};

const loadTextLayoutContract = async (runtimeRoot) => {
  const contract = JSON.parse(await readFile(path.join(runtimeRoot, "text-layout-contract.json"), "utf8"));
  if (
    contract.schema_version !== "talkcraft-text-layout/v1" ||
    contract.allowed_plane !== "text.screen" ||
    contract.measurement !== "rendered-node-dom-range-and-scroll" ||
    contract.overflow_policy !== "reject"
  ) throw new Error("text layout contract is invalid");
  return contract;
};

const loadTimeDomainContract = async (runtimeRoot) => {
  const contract = JSON.parse(await readFile(path.join(runtimeRoot, "time-domain-contract.json"), "utf8"));
  if (
    contract.schema_version !== "talkcraft-time-domain/v1" ||
    contract.timeline_fps !== 24 ||
    contract.frame_intervals !== "half-open" ||
    contract.seconds_input !== "finite-non-negative-timestamp" ||
    contract.seconds_to_frame_quantization !== "round-half-even" ||
    contract.media_policy?.supported_source_timebase !== "cfr" ||
    contract.playback_bridge?.renderer !== "remotion-offthread-video" ||
    JSON.stringify(contract.playback_bridge?.supported_playback_rates) !== JSON.stringify([1]) ||
    contract.playback_bridge?.supported_source_fps !== "positive-integer-cfr" ||
    contract.playback_bridge?.source_start_alignment !== "exact-composition-frame" ||
    contract.playback_bridge?.verified_fixture?.path !== "public/time-domain-cfr-20fps.mp4" ||
    contract.playback_bridge?.verified_fixture?.sha256 !== "d0789219eae5aafa2bc178da7f79c317473a79a09780d6089fd8c1dde005ec26" ||
    contract.production_brief_connected !== false
  ) throw new Error("time domain contract is invalid");
  return contract;
};

const loadDeterminismContract = async (runtimeRoot) => {
  const contract = JSON.parse(await readFile(path.join(runtimeRoot, "determinism-contract.json"), "utf8"));
  if (
    contract.schema_version !== "talkcraft-determinism/v1" ||
    contract.timeline_fps !== 24 ||
    contract.animation_time_domain !== "resolved-animation-local-frame" ||
    contract.animejs?.version !== "4.5.0" ||
    contract.three?.version !== "0.186.0" ||
    contract.three?.chromium_gl !== "angle" ||
    JSON.stringify(contract.probe?.animation_local_frames) !== JSON.stringify([0, 24, 47]) ||
    contract.probe?.scene_global_start !== 48 ||
    contract.production_brief_connected !== false
  ) throw new Error("determinism contract is invalid");
  return contract;
};

const loadQualificationCase = async (runtimeRoot, cardId, caseId) => {
  if (!CARD_ID.test(cardId) || !CARD_ID.test(caseId)) throw new Error("qualification candidate identity is invalid");
  const cases = JSON.parse(await readFile(path.join(runtimeRoot, "qualification-cases", `${cardId}.json`), "utf8"));
  const selected = Array.isArray(cases.cases) ? cases.cases.find((item) => item?.case_id === caseId) : null;
  const modulePath = path.join(runtimeRoot, "src", "cards", `${cardId}.tsx`);
  const contractPath = path.join(runtimeRoot, "src", "cards", `${cardId}.contract.json`);
  const moduleBytes = await readFile(modulePath);
  const contractBytes = await readFile(contractPath);
  const contract = JSON.parse(contractBytes.toString("utf8"));
  const fixtures = JSON.parse(await readFile(path.join(runtimeRoot, "qualification-fixtures.json"), "utf8"));
  const fixtureById = new Map(Array.isArray(fixtures.assets) ? fixtures.assets.map((asset) => [asset.asset_id, asset]) : []);
  const cueKeys = "anchor,assetKey,cueId,frame,name,playbackRate,volume";
  const validCue = (cue, duration) => cue !== null && typeof cue === "object" && Object.keys(cue).sort().join(",") === cueKeys &&
    CARD_ID.test(cue.cueId) && CARD_ID.test(cue.anchor) && CARD_ID.test(cue.name) && CARD_ID.test(cue.assetKey) &&
    Number.isInteger(cue.frame) && cue.frame >= 0 && cue.frame < duration && Number.isFinite(cue.volume) && cue.volume > 0 && cue.volume <= 1 &&
    Number.isFinite(cue.playbackRate) && cue.playbackRate >= 0.5 && cue.playbackRate <= 2;
  const rect = selected?.scene?.presenterRect;
  const validRect = rect !== null && typeof rect === "object" && Object.keys(rect).sort().join(",") === "height,width,x,y" &&
    [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) && rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0 &&
    rect.x + rect.width <= 1080 && rect.y + rect.height <= 1920;
  const caseCueKeys = "anchor,assetKey,cueId,frame,name,playbackRate,sha256,src,volume";
  const strippedCues = Array.isArray(selected?.sfx) ? selected.sfx.map(({src: _src, sha256: _sha256, ...cue}) => cue) : null;
  const cuesMatchFixtures = Array.isArray(selected?.sfx) && selected.sfx.every((cue) => {
    const asset = fixtureById.get(cue?.assetKey);
    return cue !== null && typeof cue === "object" && Object.keys(cue).sort().join(",") === caseCueKeys &&
      asset?.public_path === cue.src && asset?.sha256 === cue.sha256;
  });
  const presenterAsset = Array.from(fixtureById.values()).find((asset) => asset?.public_path === selected?.presenter?.src);
  const sceneInputSlots = contract.scene_input_slots ?? [];
  const sceneInputKeys = "fixture_id,kind,slot";
  const sceneInputKinds = new Map([["presenter-on-white", "video-alpha"], ["presenter-alpha", "video-alpha"], ["video-cover", "video"], ["image-contain", "image"]]);
  const validSceneInputs = Array.isArray(selected?.scene_inputs) && selected.scene_inputs.every((input) => {
    const asset = fixtureById.get(input?.fixture_id);
    return input !== null && typeof input === "object" && Object.keys(input).sort().join(",") === sceneInputKeys &&
      CARD_ID.test(input.slot) && CARD_ID.test(input.fixture_id) && sceneInputKinds.get(input.kind) === asset?.kind;
  });
  const resolvedSceneInputs = validSceneInputs ? selected.scene_inputs.map((input) => {
    const asset = fixtureById.get(input.fixture_id);
    return asset.kind === "image" || input.kind === "presenter-alpha"
      ? {slot: input.slot, kind: input.kind, src: asset.public_path, sha256: asset.sha256, width: asset.width, height: asset.height}
      : {slot: input.slot, kind: input.kind, src: asset.public_path, sha256: asset.sha256};
  }) : [];
  const sameFields = (left, right, keys) => {
    const valid = (value) => value !== null && typeof value === "object" && !Array.isArray(value) &&
      Object.keys(value).sort().join(",") === [...keys].sort().join(",") &&
      keys.every((key) => Number.isFinite(value[key]));
    return valid(left) && valid(right) && keys.every((key) => left[key] === right[key]);
  };
  const sameRect = (left, right) => sameFields(left, right, ["x", "y", "width", "height"]);
  const sameSize = (left, right) => sameFields(left, right, ["width", "height"]);
  const sameRectList = (left, right) => Array.isArray(left) && Array.isArray(right) &&
    left.length === right.length && left.every((rect, index) => sameRect(rect, right[index]));
  const trustedGeometryValid = contract.trusted_geometry === undefined || (() => {
    if (contract.trusted_geometry === "case-measured-alpha-overlap-v1") {
      const geometry = contract.geometry;
      const measurement = selected?.measurement;
      const presenterInput = selected?.scene_inputs?.find((input) => input.slot === "presenter");
      const presenter = fixtureById.get(presenterInput?.fixture_id);
      const trustedAlpha = TRUSTED_ALPHA_GEOMETRY.get(presenter?.sha256);
      const rectKeys = "height,width,x,y";
      const validBoundedRect = (rect, width, height) => rect !== null && typeof rect === "object" && Object.keys(rect).sort().join(",") === rectKeys &&
        [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) && rect.x >= 0 && rect.y >= 0 && rect.width > 0 && rect.height > 0 && rect.x + rect.width <= width && rect.y + rect.height <= height;
      if (geometry === null || typeof geometry !== "object" || Object.keys(geometry).sort().join(",") !== "max_overlap_ratio,method,min_overlap_ratio,presenter_rect,source_alpha_bbox,title_rect" ||
          measurement === null || typeof measurement !== "object" || Object.keys(measurement).sort().join(",") !== "fixture_id,mapped_alpha_bbox,method,overlap_ratio,presenter_rect,source_alpha_bbox,source_size,title_rect" ||
          !trustedAlpha || geometry.method !== trustedAlpha.method || measurement.method !== geometry.method ||
          presenterInput?.kind !== "presenter-alpha" || presenter?.kind !== "video-alpha" || measurement.fixture_id !== presenterInput.fixture_id ||
          presenter.width !== trustedAlpha.width || presenter.height !== trustedAlpha.height ||
          !sameRect(geometry.source_alpha_bbox, trustedAlpha.sourceAlphaBBox) ||
          !sameSize(measurement.source_size, {width: presenter.width, height: presenter.height}) ||
          !sameRect(measurement.source_alpha_bbox, geometry.source_alpha_bbox) ||
          !sameRect(measurement.presenter_rect, geometry.presenter_rect) ||
          !sameRect(measurement.title_rect, geometry.title_rect) ||
          !Number.isFinite(geometry.min_overlap_ratio) || geometry.min_overlap_ratio < 0.1 || geometry.min_overlap_ratio > 0.22 ||
          !Number.isFinite(geometry.max_overlap_ratio) || geometry.max_overlap_ratio < geometry.min_overlap_ratio || geometry.max_overlap_ratio > 0.22 ||
          !validBoundedRect(geometry.source_alpha_bbox, presenter.width, presenter.height) ||
          !validBoundedRect(geometry.presenter_rect, 1080, 1920) || !validBoundedRect(geometry.title_rect, 1080, 1920)) return false;
      const scale = Math.min(geometry.presenter_rect.width / presenter.width, geometry.presenter_rect.height / presenter.height);
      const mapped = {
        x: geometry.presenter_rect.x + (geometry.presenter_rect.width - presenter.width * scale) / 2 + geometry.source_alpha_bbox.x * scale,
        y: geometry.presenter_rect.y + geometry.presenter_rect.height - presenter.height * scale + geometry.source_alpha_bbox.y * scale,
        width: geometry.source_alpha_bbox.width * scale,
        height: geometry.source_alpha_bbox.height * scale,
      };
      const overlapWidth = Math.max(0, Math.min(mapped.x + mapped.width, geometry.title_rect.x + geometry.title_rect.width) - Math.max(mapped.x, geometry.title_rect.x));
      const overlapHeight = Math.max(0, Math.min(mapped.y + mapped.height, geometry.title_rect.y + geometry.title_rect.height) - Math.max(mapped.y, geometry.title_rect.y));
      const overlapRatio = overlapWidth * overlapHeight / (geometry.title_rect.width * geometry.title_rect.height);
      return sameRect(measurement.mapped_alpha_bbox, mapped) && Math.abs(measurement.overlap_ratio - overlapRatio) < 1e-12 && overlapRatio >= geometry.min_overlap_ratio && overlapRatio <= geometry.max_overlap_ratio;
    }
    if (contract.trusted_geometry !== "case-measured-targets-v1") return false;
    const measurement = selected?.measurement;
    const imageInput = selected?.scene_inputs?.find((input) => input.slot === "subject-image");
    const imageAsset = fixtureById.get(imageInput?.fixture_id);
    const annotations = selected?.raw?.annotations;
    return measurement !== null && typeof measurement === "object" &&
      Object.keys(measurement).sort().join(",") === "fixture_id,label_rects,method,source_size,target_boxes" &&
      measurement.fixture_id === imageInput?.fixture_id && imageAsset?.kind === "image" &&
      measurement.method === "opencv-canny-contour-v1" &&
      sameSize(measurement.source_size, {width: imageAsset.width, height: imageAsset.height}) &&
      Array.isArray(annotations) &&
      sameRectList(measurement.target_boxes, annotations.map((annotation) => annotation.targetBox)) &&
      sameRectList(measurement.label_rects, annotations.map((annotation) => annotation.labelRect));
  })();
  if (
    cases.schema_version !== "talkcraft-qualification-cases/v2" || cases.card_id !== cardId ||
    typeof cases.adapter_version !== "string" || cases.adapter_version.length === 0 ||
    !/^[0-9a-f]{64}$/.test(cases.implementation_sha256) || sha256(moduleBytes) !== cases.implementation_sha256 ||
    !/^[0-9a-f]{64}$/.test(cases.contract_sha256) || sha256(contractBytes) !== cases.contract_sha256 ||
    contract.schema_version !== "talkcraft-card-contract/v1" || contract.card_id !== cardId ||
    !new Set(["portrait-stack", "full-frame"]).has(contract.scene) || !Array.isArray(contract.sfx_cues) || contract.sfx_cues.length > 8 ||
    !Array.isArray(sceneInputSlots) || sceneInputSlots.length > 8 || sceneInputSlots.some((slot) => !CARD_ID.test(slot)) || new Set(sceneInputSlots).size !== sceneInputSlots.length ||
    !selected || !Number.isInteger(selected.duration_frames) || selected.duration_frames < 1 || selected.duration_frames > 720 ||
    selected.scene?.layout !== contract.scene || (contract.scene === "portrait-stack" && (!validRect || !presenterAsset || presenterAsset.sha256 !== selected.presenter?.sha256)) ||
    (contract.scene === "full-frame" && (rect !== null || selected.presenter !== null)) ||
    !validSceneInputs || JSON.stringify(selected.scene_inputs.map((input) => input.slot)) !== JSON.stringify(sceneInputSlots) ||
    !trustedGeometryValid ||
    contract.sfx_cues.some((cue) => !validCue(cue, selected.duration_frames)) || new Set(contract.sfx_cues.map((cue) => cue.cueId)).size !== contract.sfx_cues.length ||
    !cuesMatchFixtures || JSON.stringify(strippedCues) !== JSON.stringify(contract.sfx_cues)
  ) throw new Error("qualification candidate contract is invalid");
  return {cases, selected, modulePath, contract, resolvedSceneInputs};
};

const exactObject = (value, keys) => value !== null && typeof value === "object" && !Array.isArray(value) &&
  JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort());

const stageProductionMedia = async ({manifestPath, resolved}) => {
  if (typeof manifestPath !== "string" || !MEDIA_FD.test(manifestPath)) {
    throw new Error("[PRODUCTION_MEDIA_INVALID] inherited media manifest is required");
  }
  const manifestBytes = await readFile(manifestPath);
  if (manifestBytes.length === 0 || manifestBytes.length > 64 * 1024) {
    throw new Error("[PRODUCTION_MEDIA_INVALID] media manifest size is invalid");
  }
  let manifest;
  try { manifest = JSON.parse(manifestBytes.toString("utf8")); } catch {
    throw new Error("[PRODUCTION_MEDIA_INVALID] media manifest is not valid JSON");
  }
  if (!exactObject(manifest, ["schema_version", "brief_sha256", "media"]) ||
      manifest.schema_version !== "reference-process-media/v1" ||
      manifest.brief_sha256 !== resolved.briefSha256 || !Array.isArray(manifest.media) ||
      manifest.media.length !== resolved.brief.media.length || manifest.media.length > 8) {
    throw new Error("[PRODUCTION_MEDIA_INVALID] media manifest differs from the production brief");
  }
  const publicDir = await mkdtemp(path.join(tmpdir(), "talkcraft-production-public-"));
  await mkdir(path.join(publicDir, "production"), {recursive: true});
  try {
    const stagedMedia = [];
    const refs = new Set();
    const stagedPaths = new Set();
    for (let index = 0; index < manifest.media.length; index += 1) {
      const item = manifest.media[index];
      const expected = resolved.brief.media[index];
      if (!exactObject(item, ["media_ref", "fd", "sha256", "byte_length"]) ||
          item.media_ref !== `media-${index}` || refs.has(item.media_ref) ||
          !Number.isInteger(item.fd) || item.fd < 3 || !HASH.test(item.sha256) ||
          !Number.isInteger(item.byte_length) || item.byte_length < 1 || item.byte_length > 512 * 1024 * 1024 ||
          item.sha256 !== expected.sha256) {
        throw new Error("[PRODUCTION_MEDIA_INVALID] media binding is invalid");
      }
      refs.add(item.media_ref);
      const fdPath = `/dev/fd/${item.fd}`;
      const bytes = await readFile(fdPath);
      if (bytes.length !== item.byte_length || sha256(bytes) !== item.sha256) {
        throw new Error("[PRODUCTION_MEDIA_INVALID] inherited media content changed");
      }
      const extension = path.extname(expected.job_path).toLowerCase();
      if (!MEDIA_EXTENSION.has(extension)) throw new Error("[PRODUCTION_MEDIA_INVALID] media extension is unsupported");
      const relative = `production/${item.sha256}${extension}`;
      if (!stagedPaths.has(relative)) {
        await writeFile(path.join(publicDir, relative), bytes, {flag: "wx"});
        stagedPaths.add(relative);
      }
      stagedMedia.push({mediaRef: item.media_ref, publicSrc: relative});
    }
    return {publicDir, stagedMedia};
  } catch (error) {
    await rm(publicDir, {recursive: true, force: true});
    throw error;
  }
};

const renderProduction = async ({args, runtimeRoot, resolved}) => {
  if (!path.isAbsolute(args.output ?? "") || !path.isAbsolute(args.browser ?? "")) {
    throw new Error("[PRODUCTION_INPUT_INVALID] output and browser must be absolute");
  }
  const browserInfo = await stat(args.browser);
  if (!browserInfo.isFile()) throw new Error("browser is unavailable");
  const staged = await stageProductionMedia({manifestPath: args["media-manifest"], resolved});
  try {
    const generated = `import * as card from "./cards/${resolved.brief.card_id}";\nimport adapt from "./production-adapters/${resolved.brief.card_id}";\nimport {registerBriefProductionCard} from "./production-card-root";\nregisterBriefProductionCard(card, adapt);\n`;
    const entryPoint = path.join(runtimeRoot, "src", "production-entry.tsx");
    await writeFile(entryPoint, generated, {flag: "wx"});
    const serveUrl = await bundle({entryPoint, publicDir: staged.publicDir, ignoreRegisterRootWarning: true});
    const inputProps = {brief: resolved.brief, stagedMedia: staged.stagedMedia};
    const composition = await selectComposition({
      serveUrl, id: "TalkCraftProductionCard", inputProps,
      browserExecutable: args.browser, chromiumOptions: {gl: "angle"},
    });
    const frames = resolved.brief.render.duration_frames;
    const alpha = resolved.brief.render.alpha;
    const descriptorOutput = path.dirname(args.output) === "/dev/fd";
    const renderOutput = descriptorOutput
      ? path.join(runtimeRoot, `talkcraft-production-output.${alpha ? "mov" : "mp4"}`)
      : args.output;
    await renderMedia({
      serveUrl, composition, codec: alpha ? "prores" : "h264",
      proResProfile: alpha ? "4444" : undefined,
      pixelFormat: alpha ? "yuva444p10le" : "yuv420p",
      outputLocation: renderOutput, inputProps,
      browserExecutable: args.browser, chromiumOptions: {gl: "angle"},
      concurrency: 1, imageFormat: "png", muted: true, overwrite: false,
    });
    const output = await readFile(renderOutput);
    if (descriptorOutput) await writeFile(args.output, output);
    process.stdout.write(`${JSON.stringify({
      schema_version: "talkcraft-production-result/v1", runtime_version: VERSION,
      renderer_version: "4.0.520", card_id: resolved.brief.card_id,
      qualification_id: resolved.card.production.qualification_id,
      alpha, width: 1080, height: 1920, fps: 24, frame_count: frames,
      output_sha256: sha256(output), output_bytes: output.length,
    })}\n`);
  } finally {
    await rm(staged.publicDir, {recursive: true, force: true});
  }
};

export const run = async (argv, {runtimeRoot}) => {
  const args = parseArgs(argv);
  if (args["runtime-root"] === undefined || path.resolve(args["runtime-root"]) !== runtimeRoot) {
    throw new Error("runtime root differs from the verified snapshot");
  }
  if (args.brief !== undefined) {
    if (args["probe-mechanism"] !== undefined || args["probe-foundation"] !== undefined || args["probe-scene"] !== undefined || args["probe-text-layout"] !== undefined || args["probe-time-domain"] !== undefined || args["probe-determinism"] !== undefined || args["probe-card"] !== undefined) {
      throw new Error("[UNSUPPORTED_BRIEF_KIND] production and mechanism probe inputs cannot be mixed");
    }
    const resolved = await resolveProductionCard({
      briefPath: args.brief,
      registryPath: path.join(runtimeRoot, "card-registry.json"),
      runtimeRoot,
    });
    await renderProduction({args, runtimeRoot, resolved});
    return;
  }
  const mechanism = args["probe-mechanism"];
  const foundation = args["probe-foundation"];
  const scene = args["probe-scene"];
  const textLayout = args["probe-text-layout"];
  const timeDomain = args["probe-time-domain"];
  const determinism = args["probe-determinism"];
  const cardProbe = args["probe-card"];
  if ([mechanism, foundation, scene, textLayout, timeDomain, determinism, cardProbe].filter((value) => value !== undefined).length !== 1) {
    throw new Error("exactly one probe kind is required");
  }
  if (mechanism !== undefined && !MODES.has(mechanism)) throw new Error("probe mechanism is invalid");
  if (foundation !== undefined && !new Set(["backdrop", "frame"]).has(foundation)) {
    throw new Error("probe foundation is invalid");
  }
  if (scene !== undefined && scene !== "layout-camera") throw new Error("probe scene is invalid");
  if (textLayout !== undefined && !new Set(["valid", "overflow", "presenter", "world", "hidden"]).has(textLayout)) {
    throw new Error("probe text layout is invalid");
  }
  if (timeDomain !== undefined && timeDomain !== "timeline-anchor-media") throw new Error("probe time domain is invalid");
  if (determinism !== undefined && determinism !== "bridge-isolation") throw new Error("probe determinism is invalid");
  if (cardProbe !== undefined && (!CARD_ID.test(cardProbe) || args.case === undefined)) throw new Error("qualification candidate identity is invalid");
  if (cardProbe === undefined && args.case !== undefined) throw new Error("qualification case requires a card probe");
  if (foundation === undefined && scene === undefined && timeDomain === undefined && determinism === undefined && args["sample-order"] !== undefined) {
    throw new Error("sample order is only valid for a foundation, scene, time domain, or determinism probe");
  }
  const foundationContract = foundation === undefined ? null : await loadFoundationContract(runtimeRoot);
  const sceneContract = scene === undefined ? null : await loadSceneContract(runtimeRoot);
  if (textLayout !== undefined) await loadTextLayoutContract(runtimeRoot);
  if (timeDomain !== undefined) await loadTimeDomainContract(runtimeRoot);
  const determinismContract = determinism === undefined ? null : await loadDeterminismContract(runtimeRoot);
  const candidate = cardProbe === undefined ? null : await loadQualificationCase(runtimeRoot, cardProbe, args.case);
  const sampleOrder = args["sample-order"] ?? "sequential";
  if ((foundation !== undefined || scene !== undefined || timeDomain !== undefined || determinism !== undefined) && !new Set(["sequential", "shuffled"]).has(sampleOrder)) {
    throw new Error("sample order is invalid");
  }
  const sourceFrames = determinism !== undefined
    ? (sampleOrder === "shuffled" ? [47, 0, 24] : determinismContract.probe.animation_local_frames)
    : timeDomain !== undefined
    ? (sampleOrder === "shuffled" ? [95, 48, 72] : [48, 72, 95])
    : scene === undefined
      ? (sampleOrder === "shuffled" ? [48, 0, 24] : [0, 24, 48])
      : (sampleOrder === "shuffled" ? [71, 0, 36] : sceneContract.probe.source_frames);
  const variants = foundation === undefined ? null : foundationContract[foundation === "frame" ? "frames" : "backdrops"];
  const sceneVariants = scene === undefined ? null : sceneContract.probe.variants;
  const frames = foundation !== undefined
    ? variants.length * sourceFrames.length
    : scene !== undefined ? sceneVariants.length * sourceFrames.length
      : textLayout !== undefined ? 1 : timeDomain !== undefined || determinism !== undefined ? 3
        : cardProbe !== undefined ? candidate.selected.duration_frames : Number(args.frames ?? 48);
  if (!Number.isInteger(frames) || frames < 1 || frames > 720) {
    throw new Error("frames must be an integer in [1,720]");
  }
  const alpha = args.alpha === "true";
  if (args.alpha !== "true" && args.alpha !== "false") throw new Error("alpha must be true or false");
  if (mechanism === "annotation" && !alpha) throw new Error("annotation probe requires alpha");
  if (cardProbe !== undefined && alpha) throw new Error("qualification card composite probe requires opaque output");
  if (mechanism !== "annotation" && alpha) throw new Error("only annotation probes may use alpha");
  if (!path.isAbsolute(args.output)) throw new Error("output must be absolute");
  if (!path.isAbsolute(args.browser)) throw new Error("browser must be absolute");
  const browserInfo = await stat(args.browser);
  if (!browserInfo.isFile()) throw new Error("browser is unavailable");
  const numericValue = Number(args.value ?? 108);
  if (!Number.isFinite(numericValue)) throw new Error("value must be finite");

  let entryPoint = path.join(runtimeRoot, "src/index.tsx");
  let generatedEntrySha256 = null;
  if (cardProbe !== undefined) {
    const generated = `import * as card from "./cards/${cardProbe}";\nimport {registerProductionCard} from "./production-card-root";\nregisterProductionCard(card);\n`;
    entryPoint = path.join(runtimeRoot, "src", "qualification-entry.tsx");
    await writeFile(entryPoint, generated, {flag: "wx"});
    generatedEntrySha256 = sha256(Buffer.from(generated));
  }
  const serveUrl = await bundle({
    entryPoint,
    publicDir: path.join(runtimeRoot, "public"),
    ignoreRegisterRootWarning: cardProbe !== undefined,
  });
  const inputProps = mechanism !== undefined ? {
    mode: mechanism, alpha, title: args.title ?? "TalkCraft", value: numericValue,
    namespace: `talkcraft-${mechanism}-probe`, durationInFrames: frames,
  } : foundation !== undefined ? {
    kind: foundation, sourceFrames,
    namespace: `talkcraft-${foundation}-foundation-probe`, durationInFrames: frames,
  } : scene !== undefined ? {
    sourceFrames, durationInFrames: frames,
  } : timeDomain !== undefined ? {
    globalFrames: sourceFrames, durationInFrames: frames,
  } : determinism !== undefined ? {
    animationLocalFrames: sourceFrames, durationInFrames: frames,
  } : cardProbe !== undefined ? {
    cardId: cardProbe, caseId: args.case, raw: candidate.selected.raw, durationInFrames: frames,
    scene: candidate.selected.scene, presenter: candidate.selected.presenter, sceneInputs: candidate.resolvedSceneInputs, sfx: candidate.selected.sfx,
  } : {
    mode: textLayout, durationInFrames: frames,
  };
  const composition = await selectComposition({
    serveUrl,
    id: mechanism !== undefined ? "TalkCraftMechanismProbe"
      : foundation !== undefined ? "TalkCraftFoundationProbe"
        : scene !== undefined ? "TalkCraftSceneFoundationProbe"
          : timeDomain !== undefined ? "TalkCraftTimeDomainProbe"
            : determinism !== undefined ? "TalkCraftDeterminismProbe"
              : cardProbe !== undefined ? "TalkCraftQualificationCandidate" : "TalkCraftTextLayoutProbe",
    inputProps,
    browserExecutable: args.browser,
    chromiumOptions: {gl: "angle"},
  });
  const descriptorOutput = path.dirname(args.output) === "/dev/fd";
  const renderOutput = descriptorOutput
    ? path.join(runtimeRoot, `talkcraft-render-output.${alpha ? "mov" : "mp4"}`)
    : args.output;
  await renderMedia({
    serveUrl,
    composition,
    codec: alpha ? "prores" : "h264",
    proResProfile: alpha ? "4444" : undefined,
    pixelFormat: alpha ? "yuva444p10le" : "yuv420p",
    outputLocation: renderOutput,
    inputProps,
    browserExecutable: args.browser,
    chromiumOptions: {gl: "angle"},
    concurrency: 1,
    imageFormat: "png",
    muted: cardProbe === undefined,
    audioCodec: cardProbe !== undefined ? "aac" : undefined,
    overwrite: false,
  });
  const output = await readFile(renderOutput);
  if (descriptorOutput) await writeFile(args.output, output);
  const result = {
    schema_version: mechanism !== undefined ? "talkcraft-runtime-probe-result/v1"
      : foundation !== undefined ? "talkcraft-runtime-foundation-result/v1"
        : scene !== undefined ? "talkcraft-runtime-scene-result/v1"
          : timeDomain !== undefined ? "talkcraft-runtime-time-domain-result/v1"
            : determinism !== undefined ? "talkcraft-runtime-determinism-result/v1"
              : cardProbe !== undefined ? "talkcraft-qualification-candidate-result/v1" : "talkcraft-runtime-text-layout-result/v1",
    runtime_version: VERSION,
    renderer_version: "4.0.520",
    alpha,
    width: 1080,
    height: 1920,
    fps: 24,
    frame_count: frames,
    output_sha256: sha256(output),
    output_bytes: output.length,
    ...(mechanism !== undefined ? {mechanism} : foundation !== undefined ? {
      foundation, variants, source_frames: sourceFrames, sample_order: sampleOrder,
    } : scene !== undefined
      ? {scene, variants: sceneVariants, source_frames: sourceFrames, sample_order: sampleOrder}
      : timeDomain !== undefined
        ? {time_domain: timeDomain, global_frames: sourceFrames, sample_order: sampleOrder}
        : determinism !== undefined
          ? {determinism, animation_local_frames: sourceFrames, scene_global_start: determinismContract.probe.scene_global_start, sample_order: sampleOrder}
          : cardProbe !== undefined
            ? {card_id: cardProbe, case_id: args.case, adapter_version: candidate.cases.adapter_version, implementation_sha256: candidate.cases.implementation_sha256, contract_sha256: candidate.cases.contract_sha256, generated_entry_sha256: generatedEntrySha256, presenter_fixture_sha256: candidate.selected.presenter?.sha256 ?? null, presenter_decode: candidate.selected.presenter || candidate.selected.scene_inputs.some((input) => input.kind === "presenter-alpha") ? "vp9-alpha-transparent" : null, scene_input_fixture_sha256: candidate.resolvedSceneInputs.map((input) => input.sha256), layout: candidate.selected.scene.layout, sfx_cues: candidate.selected.sfx.map(({src: _src, sha256: _sha256, ...cue}) => cue), qualification_granted: false}
            : {text_layout: textLayout}),
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
};
