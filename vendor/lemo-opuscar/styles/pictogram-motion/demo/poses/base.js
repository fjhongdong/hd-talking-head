// Pose library conventions (shared by all poses/*.js)
//
// POSES[name] = {
//   pose(u) → pose object         u = beats since this card started (150 BPM, 1 beat 0.4s; cards are 4 beats, fast-cut cards 2 beats)
//            or keys: [...] + loop: beats   (see G.keyPose)
//   back(ctx, J, u, C)   optional, props/environment drawn behind the figure (unit = body height, origin = hips)
//   front(ctx, J, u, C)  optional, props drawn in front of the figure
//   fig: optional { s: scale, x, y }  offset of the figure on the stage (in body heights)
//   second: optional (u) → pose     a second person (opponent / teammate), drawn behind the main figure in colour C.far2
//   secondX: second person's offset [x, y], secondFace: -1 means facing left
// }
// C = { fg near-side colour, far far-side colour, far2 second-person colour, acc accent colour, bg background colour, line thin-line colour }
// Design language: the geometry of the official core graphic — props are circles, half circles, capsule segments and straight lines; no realistic detail.
// Movement must lock to the beat: u = 0,1,2,3 are the strong beats; key actions (release, hit, landing) fall on whole beats.
window.POSES = window.POSES || {};

(function () {
  const G = window.G;
  // Common props
  G.P = {
    ball: (ctx, x, y, r, C, o = {}) => {
      G.disc(ctx, x, y, r, o.col || C.acc);
      if (o.seam !== false) { ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.clip(); G.disc(ctx, x + r * 0.9, y - r * 0.9, r * 0.95, o.col2 || C.bg); ctx.restore(); }
    },
    racket: (ctx, hand, ang, len, headR, C, o = {}) => {
      // ang: degrees, 0 = down, 90 = forward
      const d = [Math.sin(ang * G.D2R), Math.cos(ang * G.D2R)];
      const tip = [hand[0] + d[0] * len, hand[1] + d[1] * len];
      G.seg(ctx, hand, tip, 0.022, o.col || C.fg);
      const hc = [tip[0] + d[0] * headR, tip[1] + d[1] * headR];
      ctx.save(); ctx.translate(hc[0], hc[1]); ctx.rotate(-ang * G.D2R);
      ctx.strokeStyle = o.col || C.fg; ctx.lineWidth = 0.02;
      ctx.beginPath(); ctx.ellipse(0, 0, headR * 0.78, headR, 0, 0, Math.PI * 2); ctx.stroke();
      if (o.solid) { ctx.fillStyle = o.col || C.fg; ctx.fill(); }
      ctx.restore();
      return hc;
    },
    stick: (ctx, a, b, w, C, col) => G.seg(ctx, a, b, w, col || C.fg),
    ground: (ctx, y, C, x0 = -1.2, x1 = 1.2) => { ctx.fillStyle = C.line; ctx.fillRect(x0, y, x1 - x0, 0.012); },
    // Speed lines: n lines trailing back from (x,y)
    speed: (ctx, x, y, len, n, C, a = 1) => {
      ctx.save(); ctx.globalAlpha *= a;
      for (let i = 0; i < n; i++) { ctx.fillStyle = C.line; ctx.fillRect(x - len * (0.6 + 0.4 * ((i * 37) % 10) / 10), y + (i - (n - 1) / 2) * 0.07, len * (0.5 + 0.5 * ((i * 53) % 10) / 10), 0.012); }
      ctx.restore();
    },
    // Flight arc of an object (0→1)
    arc: (a, b, h, t) => [G.lerp(a[0], b[0], t), G.lerp(a[1], b[1], t) - h * 4 * t * (1 - t)],
  };
})();
