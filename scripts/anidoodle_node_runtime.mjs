// Resolve the unchanged native engine's one bare ESM build dependency from the
// package runtime. No vendored source or global installation is changed.
import { registerHooks } from 'node:module';
import { pathToFileURL } from 'node:url';
import { existsSync } from 'node:fs';

const entry = process.env.ANIDOODLE_ESBUILD_ENTRY;
if (!entry || !existsSync(entry)) throw new Error('Anidoodle requires its checked esbuild runtime entry');
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === 'esbuild') return { url: pathToFileURL(entry).href, shortCircuit: true };
    return nextResolve(specifier, context);
  },
});
