# Hypit native static layout

`staticLayout(track)` accepts the native chat's sealed `VisualTrack` and adds portrait scaling and intrinsic bubble sizing. The launcher binds the shared `card.css` to the native bubble selectors and writes it beside the layout module. Native message order, animation and scrolling use the resulting bubble heights. The logical frame is 540×480, scaled into a 1080×1920 canvas.

`src/author.mjs` exports `authorNativeChat(input)` and `writeNativeChatBundle(dir, input)` for private `.svml`, `.svrun`, and profile files. Copy the compiled native chat package's original bytes into the job's package directory with `copyCompiledNativeChatPackage`; this package does not install or build dependencies.
