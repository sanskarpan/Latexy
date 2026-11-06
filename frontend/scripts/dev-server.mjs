import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';

// npm scripts are executed with cmd.exe on Windows, which does not expand the
// bash-style `${PORT:-5180}` default previously inlined in the `dev` script.
// Resolve the default here so `pnpm dev` works on every platform while the
// multi-slot launchers (scripts/dev.sh, worktree-up.sh) keep overriding PORT.
const port = process.env.PORT || '5180';

// Resolve the workspace-local Next.js CLI instead of relying on PATH. Running
// this file directly (`node scripts/dev-server.mjs`) does not put
// node_modules/.bin on PATH, so a bare `next` spawn fails on Windows.
const require = createRequire(import.meta.url);
const nextCli = join(dirname(require.resolve('next/package.json')), 'dist', 'bin', 'next');

const child = spawn(process.execPath, [nextCli, 'dev', '--turbopack', '-p', port], {
    stdio: 'inherit',
});

child.on('exit', (code) => process.exit(code ?? 1));

for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => child.kill(signal));
}
