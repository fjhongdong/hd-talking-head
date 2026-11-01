// "Material pass": one WebGL2 canvas + a few fragment shaders that "print / paint / display" a look's intermediate canvas.
// Usage: const out = pass('riso', srcCanvas, {u_off:[...]}); g.drawImage(out, 0, 0)
const W = 1920, H = 1080;
const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
const gl = cv.getContext('webgl2', { preserveDrawingBuffer: true, premultipliedAlpha: false, alpha: true });
if (!gl) throw new Error('no webgl2');
const VS = `#version 300 es
in vec2 p; out vec2 uv; void main(){ uv = p*.5+.5; gl_Position = vec4(p,0,1); }`;
const COMMON = `#version 300 es
precision highp float; in vec2 uv; out vec4 o;
uniform sampler2D T; uniform sampler2D T2; uniform vec2 R; uniform float time; uniform float seed;
float h21(vec2 p){ p = fract(p*vec2(123.34,456.21)); p += dot(p,p+45.32); return fract(p.x*p.y); }
float vn(vec2 p){ vec2 i=floor(p), f=fract(p); vec2 u=f*f*(3.-2.*f);
  return mix(mix(h21(i),h21(i+vec2(1,0)),u.x), mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),u.x), u.y); }
float fbm(vec2 p){ float a=.5, s=0.; for(int i=0;i<5;i++){ s+=a*vn(p); p*=2.03; a*=.5; } return s; }
vec2 px(){ return vec2(uv.x, 1.-uv.y)*R; }                 // screen pixel coordinates (origin top-left)
vec4 tex(sampler2D t, vec2 p){ return texture(t, p/R); }
uniform float layer;
`;
const FS = {
  // risograph: source canvas R = blue plate, G = yellow plate, B = pink plate density (0 = no ink)
  riso: `
uniform vec2 offB; uniform vec2 offY; uniform vec2 offP; uniform float kick;
float spot(vec2 p, float ang, float per){ float c=cos(ang), s=sin(ang); vec2 q = mat2(c,-s,s,c)*p/per; vec2 f = fract(q)-.5; return 1.-length(f)*1.414; }
float plate(float d, vec2 p, float ang, float grainSeed){
  if (d < .012) return 0.;
  float sp = spot(p, ang, 7.);
  float n = (h21(floor(p/2.)+grainSeed)-.5)*.16;
  float cov = smoothstep(-.07, .07, d - (1.-sp)*.98 + n);
  if (d > .9) cov = 1.;
  float pin = step(.965, h21(floor(p/1.5)+grainSeed*3.));
  return cov*(1.-pin*.7);
}
void main(){
  vec2 p = px();
  float dB = tex(T, p-offB).r, dY = tex(T, p-offY).g, dP = tex(T, p-offP).b;
  float streak = vn(vec2(p.x*.004, p.y*.05)+seed);
  float k = .82 + .12*streak + .06*vn(p*.01+seed*2.);
  float cB = plate(dB, p, .26, 1.)*k, cY = plate(dY, p, .0, 2.)*k, cP = plate(dP, p, 1.31, 3.)*k;
  vec3 paper = vec3(.953,.933,.890) * (1. - .03*fbm(p*.02) + .015*h21(floor(p)));
  if (layer > .5) paper = vec3(1.);
  vec3 inkB = vec3(0.0, .47, .75), inkY = vec3(1., .91, 0.), inkP = vec3(1., .28, .69);
  vec3 c = paper * mix(vec3(1), inkB, cB) * mix(vec3(1), inkY, cY) * mix(vec3(1), inkP, cP);
  o = vec4(c, 1);
}`,
  // crayon: source canvas RGB = crayon colour, A = pressure; paper tooth is generated here, anchored to the paper (page offset)
  crayon: `
uniform vec2 pageOff; uniform float pageScale;
float tooth(vec2 q){ return smoothstep(.16,.86, .5*vn(q/1.35) + .3*vn(q/2.9+7.) + .2*vn(q/6.3+3.) + .12*vn(vec2(q.x/10., q.y/1.9))); }
void main(){
  vec2 p = px(); vec2 q = (p + pageOff)/pageScale;
  float th = tooth(q);
  vec4 s = tex(T, p);
  float pr = s.a;
  float dep = smoothstep(-.07, .07, th - (1. - 1.22*pr));
  vec3 paper = vec3(.957,.937,.890) * (1. - .02*vn(q/90.) - .025*(1.-th));
  vec3 wax = s.rgb * (1. - .1*pr*pr);
  vec3 c = mix(paper, wax, dep*step(.004, pr));
  // emboss: paper tooth lit from the top-left
  float e = tooth(q - vec2(1.,1.)) - th;
  c *= 1. + e*.10*(1.-dep*.7);
  vec2 v = uv - .5; if (layer < .5) c *= 1. - dot(v,v)*.28;
  o = layer > .5 ? vec4(wax*(1.+e*.1), dep*step(.004, pr)) : vec4(c, 1);
}`,
  // amber phosphor terminal: source canvas R = brightness (white text on black)
  crt: `
uniform float on; uniform float uflat;
void main(){
  vec2 p = px();
  // barrel distortion
  vec2 c = uv - .5; float r2 = dot(c,c); vec2 duv = .5 + c*(1. + .045*r2*4.);
  if (uflat > .5) { duv = uv; r2 = 0.; }
  vec2 q = vec2(duv.x, 1.-duv.y)*R;
  float L = tex(T, q).r;
  float b = 0.; float tot = 0.;
  for (int i = 0; i < 24; i++) { float a = float(i)*2.3999; float rr = 3. + float(i)*1.1; vec2 o2 = vec2(cos(a), sin(a))*rr; float w = 1./(1.+rr*.15); b += tex(T, q+o2).r*w; tot += w; }
  b /= tot;
  float lum = L*1.15 + b*.7;
  vec3 dim = vec3(1., .40, .02), mid = vec3(1., .69, 0.), hot = vec3(1., .92, .72);
  vec3 col = lum < .6 ? mix(vec3(0), mix(dim, mid, lum/.6), smoothstep(0., .6, lum)) : mix(mid, hot, clamp((lum-.6)/.8, 0., 1.));
  float scan = .78 + .22*cos(p.y*3.14159*2./3.);
  col *= mix(scan, 1., clamp(L, 0., 1.)*.5);
  col += vec3(.035,.024,.016);   // unlit glass
  col *= 1. + (h21(p+time)-.5)*.05;
  // rounded screen mask + vignette
  vec2 m = abs(duv-.5)*2.; float mask = uflat > .5 ? 1. : smoothstep(1., .985, max(m.x, m.y)) ;
  col *= mask * (1. - r2*1.1);
  col *= on;
  o = vec4(col, 1);
}`,
  // ink wash: R = wet ink density, G = dry ink density (feibai (飞白, dry-brush streaks) / jiaomo (焦墨, scorched dark ink) lines)
  ink: `
uniform vec2 pageOff;
void main(){
  vec2 p = px(); vec2 q = p + pageOff;
  float wet0 = tex(T, p).r;
  float s1 = 0., s2 = 0.;
  for (int i = 0; i < 16; i++) { float a = float(i)*2.3999 + fbm(q*.05)*3.; float rr = 1.5 + float(i)*.45; vec2 o2 = vec2(cos(a), sin(a))*rr; s1 += tex(T, p+o2).r; }
  s1 /= 16.;
  for (int i = 0; i < 12; i++) { float a = float(i)*2.3999; float rr = 6. + float(i)*1.4; s2 += tex(T, p+vec2(cos(a), sin(a))*rr).r; }
  s2 /= 12.;
  float wet = max(wet0*.6, s1);
  float edge = clamp((s1 - s2)*1.6, 0., 1.);            // ink pooling at the edges
  float gran = (fbm(q*.35)-.5)*.18;
  float wd = clamp(wet*(1.+gran) + edge*.45*step(.05, wet), 0., 1.);
  float dry = tex(T, p).g;
  float dryB = dry * (.75 + .5*vn(q*.6));              // paper tooth breaks up the dry brush
  float d = 1. - (1.-wd)*(1.-clamp(dryB, 0., 1.));
  vec3 paper = vec3(.95,.925,.87) * (1. + .04*(fbm(q*.012)-.5)) * (1. + .018*vn(vec2(q.x*.02, q.y*.6)));
  vec3 inkc = mix(vec3(.52,.55,.58), vec3(.075,.068,.062), smoothstep(.1, .9, d));
  vec3 c;
  if (layer > .5) paper = vec3(1.);
  c = paper * mix(vec3(1.), inkc*1.08, d);
  vec2 v = uv - .5; if (layer < .5) c *= 1. - dot(v,v)*.22;
  o = vec4(c, 1);
}`,
  // blueprint paper (static, computed once)
  blueprint: `
void main(){
  vec2 p = px();
  float n = fbm(p*.0035 + seed);
  vec3 a = vec3(.094,.2,.42), b = vec3(.165,.345,.65);
  vec3 c = mix(a, b, .35 + .5*n);
  c *= 1. - .06*vn(vec2(p.x*.002, p.y*.08));
  c += (h21(floor(p))-.5)*.02;
  c *= 1. - .1*uv.x;
  vec2 v = uv - .5; c *= 1. - dot(v,v)*.5;
  o = vec4(c, 1);
}`,
};
const progs = {};
const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
function prog(name) {
  if (progs[name]) return progs[name];
  const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(name + ': ' + gl.getShaderInfoLog(s)); return s; };
  const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, COMMON + FS[name])); gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  return (progs[name] = p);
}
const texs = [gl.createTexture(), gl.createTexture()];
function upload(i, src) {
  gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, texs[i]);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
}
export function pass(name, src, u = {}, src2 = null) {
  const p = prog(name); gl.useProgram(p); gl.viewport(0, 0, W, H);
  if (src) upload(0, src); if (src2) upload(1, src2);
  gl.uniform1i(gl.getUniformLocation(p, 'T'), 0); gl.uniform1i(gl.getUniformLocation(p, 'T2'), 1);
  gl.uniform2f(gl.getUniformLocation(p, 'R'), W, H);
  const base = { time: 0, seed: 0, ...u };
  for (const [k, v] of Object.entries(base)) {
    const loc = gl.getUniformLocation(p, k); if (!loc) continue;
    if (typeof v === 'number') gl.uniform1f(loc, v); else if (v.length === 2) gl.uniform2f(loc, v[0], v[1]); else if (v.length === 3) gl.uniform3f(loc, ...v);
  }
  const loc = gl.getAttribLocation(p, 'p'); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  return cv;
}
// Offscreen 2D canvas helpers
export function canvas(w = W, h = H) { const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d', { willReadFrequently: false }); return [c, x]; }
// Static texture cache (e.g. blueprint paper): computed once and copied to a 2D canvas
const cache = {};
export function staticTex(name, u = {}) {
  if (cache[name]) return cache[name];
  const [c, x] = canvas(); pass(name, null, u); x.drawImage(cv, 0, 0); return (cache[name] = c);
}
