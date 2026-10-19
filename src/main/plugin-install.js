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

function versionOf(src) {
  return src?.match(/local VERSION = "([^"]+)"/)?.[1] || null;
}

export function bundledVersion() {
  try {
    return versionOf(pluginSource(44755));
  } catch {
    return null;
  }
}

export function pluginStatus() {
  const folder = pluginsFolder();
  const file = folder ? path.join(folder, PLUGIN_FILE) : null;
  let installed = false;
  let installedVersion = null;
  try {
    const src = fs.readFileSync(file, 'utf8');
    installed = true;
    installedVersion = versionOf(src) || '0.1.0';
  } catch {}
  const latest = bundledVersion();
  return { folder, file, installed, installedVersion, latestVersion: latest, outdated: installed && !!latest && installedVersion !== latest };
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
