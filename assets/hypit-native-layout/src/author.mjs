import { mkdir, cp, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const esc = (value) => String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export function authorNativeChat({ title, messages, frames, packageImport = "@example/chat-scene@1", layoutImport = "@hd-talking-head/hypit-native-layout@1", fontPackage = "@fontsource-variable/noto-sans-sc", durationFrames = 144, chromePath, ffmpegPath, ffprobePath }) {
  if (!title || !Array.isArray(messages) || messages.length < 2 || messages.length > 4) throw new Error("title and 2-4 messages are required");
  if (!Array.isArray(frames) || frames.length !== messages.length || frames.some((n) => !Number.isInteger(n))) throw new Error("frames must match messages");
  if (!Number.isInteger(durationFrames) || durationFrames < 120 || durationFrames > 240) throw new Error("durationFrames must be 120-240 at 24fps");
  if (!chromePath || !ffmpegPath || !ffprobePath) throw new Error("Explicit local render tools are required");
  const children = messages.map((m, i) => `    <chat:Message id="message-${i + 1}" sender="${esc(m.sender)}" side="${esc(m.side)}" at={animation.frame-${frames[i]}} text="${esc(m.text)}"/>`).join("\n");
  const instants = frames.map(frame => `    <time:Instant id="frame-${frame}" at="${frame}f"/>`).join("\n");
  const svml = `<?svml using="@hypit/markup@1"?>
<svml>
  <import as="time" from="@hypit/timeline-author@1"/>
  <import as="spatial" from="@hypit/spatial@1"/>
  <import as="media" from="@hypit/media@1"/>
  <import as="fonts" from="@hypit/fontsource@1"/>
  <import as="chat" from="${esc(packageImport)}"/>
  <import as="layout" from="${esc(layoutImport)}"/>
  <import as="film" from="@hypit/film@1"/>
  <import as="html" from="@hypit/html-video@1"/>
  <import as="style" source="./chat.svs"/>
  <time:Clock id="clock" frame-rate="24"/>
  <time:Timeline id="animation" clock={clock} end="${durationFrames}f">
${instants}
  </time:Timeline>
  <spatial:Canvas id="logical-canvas" width="540" height="480"/>
  <spatial:Canvas id="canvas" width="1080" height="1920"/>
  <fonts:Face id="font-face" package="${esc(fontPackage)}" weight="400" style="normal"/>
  <media:FontStack id="font" primary={font-face}/>
  <chat:Scene id="conversation" timeline={animation.timeline} within={logical-canvas.bounds} font={font} during={animation.window} title="${esc(title)}" entrance-frames="10">
${children}
  </chat:Scene>
  <layout:Layout id="scaled" input={conversation.visual} semantic-family="plan_change_dialogue"/>
  <film:Film id="main" canvas={canvas.canvas} timeline={animation.timeline} appearance={style.film.main}>
    <film:Track source={scaled.visual}/>
  </film:Film>
  <html:Video id="final" composition={main.composition} timeline={animation.timeline}/>
</svml>
`;
  const svrun = `<?svml using="@hypit/markup/run@1"?>
<svrun version="1">
  <author source="./chat.svml"/>
  <target output="final.video"/>
</svrun>
`;
  const profile = JSON.stringify({ format: "hypit.runtime-local@1", dataRoot: ".hypit/private-data", endpoints: {
    "media.local": { use: "@hypit/media-local", config: { defaultConcurrency: 1, ffmpegPath, ffprobePath } },
    "html.local": { use: "@hypit/provider-html-local", config: { workers: 1, defaultConcurrency: 1, chromePath, ffmpegPath, ffprobePath } },
  } }, null, 2) + "\n";
  const svs = '<?svml using="@hypit/recipe@1"?>\n<sheet version="1">\n  film.main { background: #142b32; }\n</sheet>\n';
  return { "chat.svml": svml, "chat.svs": svs, "chat.svrun": svrun, "hypit.runtime.json": profile };
}

export async function writeNativeChatBundle(directory, input) {
  const out = resolve(directory); const files = authorNativeChat(input);
  await mkdir(out, { recursive: true });
  for (const [name, contents] of Object.entries(files)) { const path = resolve(out, name); await mkdir(dirname(path), { recursive: true }); await writeFile(path, contents, "utf8"); }
  return Object.keys(files).map((name) => resolve(out, name));
}

export async function copyCompiledNativeChatPackage(sourceDirectory, destinationDirectory) {
  const source = resolve(sourceDirectory); const destination = resolve(destinationDirectory);
  await mkdir(destination, { recursive: true });
  await cp(resolve(source, "package.json"), resolve(destination, "package.json"));
  await cp(resolve(source, "dist"), resolve(destination, "dist"), { recursive: true });
}
