// Lightbox stage: scene + top LED key light (casting shadows downward) + ambient light + backlight uniforms + camera
import * as THREE from 'three';
import { vnoise } from './lib.js';

export function stage(o = {}) {
  const scene = new THREE.Scene(); scene.background = new THREE.Color(o.bg || '#000');
  const U = {
    uLight: { value: new THREE.Vector3(...(o.light || [0, .05, -.12])) }, uLightR: { value: o.lightR ?? .14 },
    uLightCol: { value: new THREE.Color(o.lightCol || '#ffe0a8') }, uLit: { value: 1 },
  };
  const cam = new THREE.PerspectiveCamera(o.fov ?? 26, 16 / 9, .01, 30);
  // Top LED: shines from above the front of the box toward the lower back, so shadows fall on the paper layers behind
  const key = new THREE.SpotLight(o.keyCol || '#ffeedd', o.key ?? 2.2, 0, o.keyAngle ?? .75, 1, 0);
  key.position.set(...(o.keyPos || [0, .34, .3])); key.target.position.set(...(o.keyTarget || [0, -.04, -.08]));
  key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -.0008; key.shadow.normalBias = 0;
  key.shadow.radius = o.shadowR ?? 10; key.shadow.blurSamples = 20; key.shadow.camera.near = .05; key.shadow.camera.far = 3;
  scene.add(key, key.target);
  const amb = new THREE.AmbientLight(o.ambCol || '#9fb0d8', o.amb ?? .5); scene.add(amb);
  const layers = [];
  return {
    scene, U, cam, key, amb, layers, base: { key: o.key ?? 2.2, amb: o.amb ?? .5 },
    add(...ms) { for (const m of ms) { scene.add(m); if (m.material?.userData?.u) layers.push(m); } return ms[0]; },
  };
}

// Camera: position / look-at point + handheld micro-motion
export function aim(cam, p, t, o = {}) {
  const h = o.hand ?? .0006, f = o.handF ?? .35;
  cam.position.set(p[0] + (vnoise(t * f + 3) - .5) * h, p[1] + (vnoise(t * f + 17) - .5) * h, p[2]);
  cam.lookAt(p[3] + (vnoise(t * f * .8 + 40) - .5) * h * .6, p[4] + (vnoise(t * f * .8 + 55) - .5) * h * .6, p[5]);
  if (o.roll) cam.rotateZ(o.roll);
  if (o.fov && cam.fov !== o.fov) { cam.fov = o.fov; cam.updateProjectionMatrix(); }
}
export const dist = (cam, z) => cam.position.z - z;

// Release the GPU resources in the scene
export function dispose(scene) {
  scene.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    const ms = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
    for (const m of ms) { for (const k of ['map', 'emissiveMap', 'alphaMap', 'bumpMap']) m[k]?.dispose?.(); m.dispose(); }
    if (o.customDepthMaterial) o.customDepthMaterial.dispose();
  });
}
