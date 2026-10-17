import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { app } from 'electron';

export const PLUGIN_FILE = 'BloxBridge.lua';

export function pluginsFolder() {
  if (process.platform === 'win32') {
    const base = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local');
    return path.join(base, 'Roblox', 'Plugins');
  }
  if (process.platform === 'darwin') return path.join(os.homedir(), 'Documents', 'Roblox', 'Plugins');
  return null; // Studio doesn't run natively on Linux
}

function pluginSource(port) {
  const dir = app.isPackaged
    ? path.join(process.resourcesPath, 'plugin')
    : path.join(app.getAppPath(), 'plugin');
  const src = fs.readFileSync(path.join(dir, PLUGIN_FILE), 'utf8');
  return src.replace('local PORT = 44755', `local PORT = ${Number(port) || 44755}`);
}

export function pluginStatus() {
  const folder = pluginsFolder();
  return { folder, installed: !!folder && fs.existsSync(path.join(folder, PLUGIN_FILE)) };
}

export function installPlugin(port) {
  const folder = pluginsFolder();
  if (!folder) throw new Error('Roblox Studio plugins folder not found on this OS. Use "Save plugin file…" instead.');
  fs.mkdirSync(folder, { recursive: true });
  const file = path.join(folder, PLUGIN_FILE);
  fs.writeFileSync(file, pluginSource(port));
  return file;
}

export function writePluginTo(file, port) {
  fs.writeFileSync(file, pluginSource(port));
  return file;
}
