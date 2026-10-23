const TOKEN = /^[a-z][a-z0-9-]{0,63}$/;
const liveNamespaces = new Map<string, Element>();

const checked = (value: string, label: string) => {
  if (!TOKEN.test(value)) throw new Error(`${label} is invalid`);
  return value;
};

export const scopedClass = (namespace: string, local: string) =>
  `${checked(namespace, "namespace")}--${checked(local, "local token")}`;

export const scopedSelector = (namespace: string, local: string) =>
  `[data-talkcraft-scope="${checked(namespace, "namespace")}"] .${scopedClass(namespace, local)}`;

export const svgId = (namespace: string, local: string) =>
  `${checked(namespace, "namespace")}--svg--${checked(local, "local token")}`;

export const svgUrl = (namespace: string, local: string) => `url(#${svgId(namespace, local)})`;

export const claimNamespace = (namespace: string, root: Element) => {
  checked(namespace, "namespace");
  const owner = liveNamespaces.get(namespace);
  if (owner && owner !== root && owner.isConnected) throw new Error(`duplicate live namespace: ${namespace}`);
  liveNamespaces.set(namespace, root);
  return () => {
    if (liveNamespaces.get(namespace) === root) liveNamespaces.delete(namespace);
  };
};

const fnv1a = (value: string) => {
  let state = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    state ^= value.charCodeAt(index);
    state = Math.imul(state, 0x01000193) >>> 0;
  }
  return state || 0x6d2b79f5;
};

export const seededUnit = (seed: string, streamKey: string, index: number) => {
  if (seed.length === 0 || streamKey.length === 0 || !Number.isInteger(index) || index < 0) {
    throw new Error("seeded stream input is invalid");
  }
  let state = fnv1a(`${seed}\u0000${streamKey}\u0000${index}`);
  state ^= state << 13;
  state ^= state >>> 17;
  state ^= state << 5;
  return (state >>> 0) / 0x100000000;
};
