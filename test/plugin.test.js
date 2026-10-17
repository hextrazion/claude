// Runs the Studio plugin against a mocked Roblox API using the Luau CLI.
// Set LUAU=/path/to/luau, or have `luau` on PATH; skipped otherwise.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';

const luau = process.env.LUAU || 'luau';
const available = spawnSync(luau, ['--help']).error === undefined;

test('Studio plugin tools', { skip: !available && 'luau CLI not found' }, () => {
  const plugin = fs.readFileSync(new URL('../plugin/BloxBridge.lua', import.meta.url), 'utf8');
  const harness = fs.readFileSync(new URL('./plugin_harness.luau', import.meta.url), 'utf8');
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bb-')), 'run.luau');
  fs.writeFileSync(file, `local PLUGIN_SOURCE = [=====[${plugin}]=====]\n${harness}`);
  const out = execFileSync(luau, [file], { encoding: 'utf8' });
  assert.match(out, /PLUGIN_HARNESS_OK 16 commands/);
});
