// Studio: dark-field glass photography lighting (black backdrop + strip softboxes); the environment map is regenerated every frame from a "light-strip scene" (a light sweep = a light strip actually moving past)
// Floor: glossy black + blurred mirror reflection + procedural caustics (the glass focuses light on the floor; they pulse with the bass and spread with the sound waves)
import * as THREE from 'three';
import { Reflector } from 'three/addons/objects/Reflector.js';

export function makeStudio(renderer, scene) {
  // —— Light-strip scene (used only to bake the environment map) ——
  const env = new THREE.Scene(); env.background = new THREE.Color('#000000');
  const strip = (w, h, I, col = '#ffffff') => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(col).multiplyScalar(I), side: THREE.DoubleSide }));
    env.add(m); return m;
  };
  const face = (m, p) => { m.position.set(...p); m.lookAt(0, 0, 0); };
  const L = {
    left: strip(22, 170, 3.2, '#f4f8ff'),        // rear-left vertical strip: traces the left outline
    right: strip(22, 170, 3.2, '#fffaf2'),       // rear-right vertical strip
    top: strip(160, 70, 1.1, '#ffffff'),         // big top softbox: gives the frosted glass and metal some volume
    front: strip(160, 50, .18, '#ffffff'),        // low front fill (very weak)
    back: strip(260, 14, 1.4, '#e8f0ff'),        // horizontal strip behind: rim light along the horizon
    sweep: strip(26, 240, 0, '#ffffff'),         // light sweep: one moving vertical strip
    aura: strip(140, 140, 0, '#62dcff'),         // coloured bounce card for when the light pattern turns on
    key: strip(150, 60, 2.5, '#ffffff'),         // top-front key softbox: key light for the metal and PCB (off by default)
  };
  face(L.left, [-150, 40, -60]); face(L.right, [150, 40, -70]); face(L.top, [0, 170, 10]);
  face(L.front, [0, 10, 170]); face(L.back, [0, 20, -190]); face(L.aura, [0, -60, 120]); face(L.key, [0, 150, 120]);
  const base = { left: 3.2, right: 3.2, top: 1.1, front: .18, back: 1.4, key: 2.5 };
  const cols = {}; for (const k in L) cols[k] = L[k].material.color.clone().multiplyScalar(1 / Math.max(.001, base[k] ?? 1));

  // Background: dark-grey radial gradient (studio sweep), strength set per shot; separates the glass edges from pure black
  const bgc = document.createElement('canvas'); bgc.width = 512; bgc.height = 288;
  { const g = bgc.getContext('2d'), gr = g.createRadialGradient(256, 120, 10, 256, 140, 300); gr.addColorStop(0, '#34383d'); gr.addColorStop(.45, '#16181b'); gr.addColorStop(1, '#000000'); g.fillStyle = gr; g.fillRect(0, 0, 512, 288); }
  const bgTex = new THREE.CanvasTexture(bgc); bgTex.colorSpace = THREE.SRGBColorSpace;
  scene.background = bgTex; scene.backgroundIntensity = 0;
  const pmrem = new THREE.PMREMGenerator(renderer);
  let envRT = null;
  // o: {k: {left,right,top,front,back}, sweep:{x (−1..1), I, ang}, aura:{I, col}}
  function updateEnv(o = {}) {
    for (const k in base) { const I = (o[k] ?? 1) * base[k]; L[k].material.color.copy(cols[k]).multiplyScalar(I); }
    const sw = o.sweep || { I: 0 };
    L.sweep.visible = sw.I > 0;
    if (sw.I > 0) {   // the strip travels left to right along an arc in front of the camera (camera space → world space: the caller supplies the azimuth)
      const a = sw.az + sw.x * 1.35, r = 170;
      L.sweep.position.set(Math.sin(a) * r, 30 + (sw.y || 0), Math.cos(a) * r); L.sweep.lookAt(0, 0, 0); L.sweep.rotateZ(sw.tilt || 0);
      L.sweep.material.color.setRGB(sw.I, sw.I, sw.I);
    }
    const au = o.aura || { I: 0 };
    L.aura.visible = au.I > 0; if (au.I > 0) L.aura.material.color.copy(au.col).multiplyScalar(au.I);
    const rt = pmrem.fromScene(env, 0, 1, 1000);
    scene.environment = rt.texture;
    if (envRT) envRT.dispose(); envRT = rt;
  }

  // —— Floor ——
  const FLOOR = { y: -15 };
  const floorShader = {
    name: 'GlassFloor',
    uniforms: {
      color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null },
      uRefl: { value: .32 }, uFade: { value: 260 }, uTime: { value: 0 },
      uC: { value: [new THREE.Vector4(0, 0, 0, 0), new THREE.Vector4(0, 0, 0, 0), new THREE.Vector4(0, 0, 0, 0)] },     // caustic sources: xz position, radius, intensity
      uWave: { value: Array.from({ length: 12 }, () => new THREE.Vector4(0, 0, 0, 0)) },   // sound-wave rings: xz, radius, intensity
      uA: { value: new THREE.Color('#62dcff') }, uB: { value: new THREE.Color('#a98bff') }, uSpot: { value: .06 },
      uCenter: { value: new THREE.Vector2(0, 0) }, uBg: { value: null }, uBgI: { value: 0 }, uRes: { value: new THREE.Vector2(3840, 2160) },
    },
    vertexShader: `uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 vW;
      void main(){ vUv = textureMatrix * vec4(position, 1.); vec4 w = modelMatrix * vec4(position, 1.); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uRefl, uFade, uTime, uSpot; uniform vec4 uC[3]; uniform vec4 uWave[12]; uniform vec3 uA, uB; uniform vec2 uCenter; uniform sampler2D uBg; uniform float uBgI; uniform vec2 uRes;
      varying vec4 vUv; varying vec3 vW;
      vec2 h2(vec2 p){ p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3))); return fract(sin(p) * 43758.5453); }
      // hand-written caustics: Voronoi edges (F2−F1) + time warp → a net of bright filaments
      float vor(vec2 p, float t){ vec2 i = floor(p), f = fract(p); float d1 = 8., d2 = 8.;
        for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) { vec2 g = vec2(float(x), float(y)); vec2 o = h2(i + g); o = .5 + .45 * sin(t + 6.2831 * o);
          float d = length(g + o - f); if (d < d1) { d2 = d1; d1 = d; } else if (d < d2) d2 = d; }
        return d2 - d1; }
      float caus(vec2 p, float t){ vec2 q = p + .55 * vec2(sin(p.y * 1.3 + t), cos(p.x * 1.1 - t * .8)); q += .25 * vec2(sin(q.y * 3.1 - t * 1.3), cos(q.x * 2.7 + t)); float e = vor(q * 1.4, t); return exp(-e * 14.) * (.6 + .4 * sin(q.x * 2. + q.y)); }
      void main(){
        vec2 xz = vW.xz; float r0 = length(xz - uCenter);
        // blurred reflection
        vec3 refl = vec3(0.); float sum = 0.;
        for (int i = 0; i < 12; i++) { float a = float(i) * 2.39996; float rr = sqrt((float(i) + .5) / 12.) * 5.;
          vec4 uv = vUv + vec4(cos(a) * rr, sin(a) * rr, 0., 0.) * vUv.w / 700.; refl += texture2DProj(tDiffuse, uv).rgb; sum += 1.; }
        refl /= sum;
        float fade = exp(-r0 * r0 / (uFade * uFade));
        vec3 col = refl * uRefl * fade;
        col += vec3(.02, .02, .021) * exp(-r0 * r0 / 9000.) * (1. + uSpot * 10.);   // a tiny pool of light under the deck
        // caustics
        for (int k = 0; k < 3; k++) { vec4 C = uC[k]; if (C.w <= 0.) continue;
          vec2 d = (xz - C.xy); float r = length(d) / C.z; float m = exp(-r * r * 1.6);
          float ring = exp(-pow((r - .72) / .07, 2.));   // ring-shaped lens caustic
          vec2 p = d / C.z * 3.2;
          vec3 c3 = vec3(caus(p * .985, uTime), caus(p, uTime), caus(p * 1.015, uTime));   // dispersion: a different scale per channel
          vec3 rr3 = vec3(exp(-pow((r - .70) / .06, 2.)), exp(-pow((r - .72) / .06, 2.)), exp(-pow((r - .74) / .06, 2.)));
          col += (c3 * m * .55 + rr3 * 1.2) * C.w * mix(vec3(1.), uA * 1.3, .3);
        }
        // sound-wave rings: coloured light rings spreading across the floor
        for (int k = 0; k < 12; k++) { vec4 Wv = uWave[k]; if (Wv.w <= 0.) continue;
          float r = length(xz - Wv.xy); float x = (r - Wv.z) / (.8 + Wv.z * .025);
          vec3 band = vec3(exp(-pow(x + .35, 2.) * 3.), exp(-x * x * 3.), exp(-pow(x - .35, 2.) * 3.));
          col += band * mix(uA, uB, clamp(Wv.z / 90., 0., 1.)) * Wv.w * exp(-r * r / 7000.);
        }
        // the far floor melts into the background gradient (seamless studio sweep)
        vec3 bgc = texture2D(uBg, gl_FragCoord.xy / uRes).rgb * uBgI;
        col = mix(bgc, col, exp(-r0 * r0 / (uFade * uFade * 2.2)));
        gl_FragColor = vec4(col, 1.);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`
  };
  const floor = new Reflector(new THREE.PlaneGeometry(2000, 2000), { shader: floorShader, textureWidth: 1920, textureHeight: 1080, clipBias: .002, multisample: 4 });
  floor.rotation.x = -Math.PI / 2; floor.position.y = FLOOR.y; scene.add(floor);
  // the mirror reflection is updated manually once per frame (otherwise the transmission pre-pass would render it again)
  const reflUpdate = floor.onBeforeRender.bind(floor); floor.onBeforeRender = () => { };
  const U = floor.material.uniforms; U.uBg.value = bgTex;
  return { env, L, updateEnv, floor, FLOOR, U, reflect(camera, hide = []) { const v = hide.map(o => o.visible); hide.forEach(o => o.visible = false); reflUpdate(renderer, scene, camera); hide.forEach((o, i) => o.visible = v[i]); } };
}
