# Hypit native static layout

`staticLayout(track)` accepts the sealed `VisualTrack` returned by native chat render and returns a new sealed track. It changes only root program styles to `scale(2)`, `transform-origin: top left`, `left: 0`, `top: 80`; native HTML/CSS/setup/data/animation and subtitle elements are retained. The intended semantic family is `plan_change_dialogue`, logical frame is 540×480, canvas is 1080×1920, 24fps, 5–10 seconds.

`src/author.mjs` exports `authorNativeChat(input)` and `writeNativeChatBundle(dir, input)` for private `.svml`, `.svrun`, and profile files. Copy the compiled native chat package's original bytes into the job's package directory with `copyCompiledNativeChatPackage`; this package does not install or build dependencies.
