# huashu-motion 工程契约

唯一来源是 [skills/huashu-motion/references/contract.md](../skills/huashu-motion/references/contract.md)。它随 skill 分发，Agent 读的就是这份。这里不再保留第二份，避免两边写得不一样。

一句话版：工程就是一个合成 `index.html`（HTML 加 GSAP，用你自己的 Chrome 逐帧渲染），用三种标注让它变得可指、可改：
- 合成变量：可以直接改的值；
- `data-om-id`：可以被指到的东西；
- 时间轴 label `scene:<id>`：分镜。
