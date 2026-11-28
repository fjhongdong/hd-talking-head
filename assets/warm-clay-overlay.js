async function createWarmClay(THREE, mount, options, designOverlay) {
  const {width, height, fps, frames, centerX, centerY, cues, style} = options;
  const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true});
  renderer.setSize(width, height);
  renderer.setClearColor(0, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  mount.append(renderer.domElement);

  const scene = new THREE.Scene();
  const halfWidth = 3.43;
  const halfHeight = halfWidth * height / width;
  const camera = new THREE.OrthographicCamera(-halfWidth, halfWidth, halfHeight, -halfHeight, .1, 75);
  camera.position.set(3.4, 10.9, 14.9);
  camera.lookAt(0, .32, 0);
  camera.setViewOffset(width, height, width / 2 - centerX, height / 2 - centerY, width, height);

  scene.add(new THREE.HemisphereLight(0xffecd6, 0xd09975, 1.77));
  const key = new THREE.DirectionalLight(0xffe7cf, 2.1);
  key.position.set(-4.8, 9.2, 4.3);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, {left: -5, right: 5, top: 5, bottom: -5, near: .5, far: 24});
  key.shadow.bias = -.0004;
  key.shadow.normalBias = .025;
  key.shadow.radius = 4.6;
  scene.add(key, key.target);
  const fill = new THREE.DirectionalLight(0xffe1c1, .77);
  fill.position.set(4, 5, -6);
  scene.add(fill);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(40, 40),
    new THREE.ShadowMaterial({opacity: .24, color: 0x77543b, depthWrite: false}));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -.02;
  floor.receiveShadow = true;
  scene.add(floor);

  const grain = clayGrain(THREE);
  const clay = (color) => new THREE.MeshStandardMaterial({
    color: style.palette[color] ?? color,
    roughness: .87, metalness: 0, bumpMap: grain, bumpScale: .021,
  });
  const roundedBlock = (w, d, h, color, radius = Math.min(w, d) * .18) => {
    const bevel = Math.min(h * .4, radius * .42);
    const shape = clayRoundedShape(THREE, w - 2 * bevel, d - 2 * bevel, radius - bevel);
    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth: h - 2 * bevel, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel,
      bevelSegments: 6, curveSegments: 16,
    });
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, bevel, 0);
    const mesh = new THREE.Mesh(geometry, clay(color));
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  };

  const pose = await designOverlay({THREE, scene, mount, palette: style.palette, clay, roundedBlock, cues});
  const {action_start_frame: start, settled_frame: settled, visible_until_frame: end} = cues;
  const framesPerPose = fps / style.motion_fps;
  let drawnFrame;
  return (time) => {
    const frame = Math.min(frames - 1, Math.max(0, Math.round(time * fps)));
    if (frame === drawnFrame) return;
    drawnFrame = frame;
    mount.hidden = frame >= end;
    if (mount.hidden) return;
    const motionFrame = frame >= settled ? settled
      : start + Math.floor(Math.max(0, frame - start) / framesPerPose) * framesPerPose;
    const progress = frame >= settled ? 1 : (motionFrame - start) / (settled - start);
    pose({frame, motionFrame, progress});
    renderer.render(scene, camera);
  };
}

function clayRoundedShape(THREE, width, depth, r) {
  const x = width / 2, y = depth / 2;
  const shape = new THREE.Shape();
  shape.moveTo(-x + r, -y);
  shape.lineTo(x - r, -y);
  shape.quadraticCurveTo(x, -y, x, -y + r);
  shape.lineTo(x, y - r);
  shape.quadraticCurveTo(x, y, x - r, y);
  shape.lineTo(-x + r, y);
  shape.quadraticCurveTo(-x, y, -x, y - r);
  shape.lineTo(-x, -y + r);
  shape.quadraticCurveTo(-x, -y, -x + r, -y);
  return shape;
}

function clayGrain(THREE) {
  const canvas = document.createElement('canvas');
  const size = canvas.width = canvas.height = 256;
  const context = canvas.getContext('2d');
  const pixels = context.createImageData(size, size);
  let seed = 87239;
  for (let i = 0; i < pixels.data.length; i += 4) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    const x = i / 4 % size, y = Math.floor(i / 4 / size);
    const value = 125 + (seed >>> 26) * .5 + Math.sin(x / 7 + Math.cos(y / 14)) * 5;
    pixels.data.set([value, value, value, 255], i);
  }
  context.putImageData(pixels, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1.22, 1.22);
  return texture;
}
