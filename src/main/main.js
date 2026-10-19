import { app, BrowserWindow, clipboard, dialog, ipcMain, shell } from 'electron';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { Store } from './store.js';
import { StudioBridge } from './bridge.js';
import { McpHub, createMcpHandler } from './mcp.js';
import { Agent } from './agent.js';
import { detectModels } from './llm.js';
import { STUDIO_TOOLS, STUDIO_TOOL_NAMES, defaultPermission } from './tools.js';
import { installPlugin, pluginStatus, pluginsFolder, writePluginTo, PLUGIN_FILE } from './plugin-install.js';

const here = path.dirname(fileURLToPath(import.meta.url));

// GUI apps on macOS don't inherit the shell PATH, so npx/uvx for MCP servers
// wouldn't be found. Add the usual install locations.
if (process.platform !== 'win32') {
  const extra = ['/usr/local/bin', '/opt/homebrew/bin', path.join(process.env.HOME || '', '.local/bin'), path.join(process.env.HOME || '', '.cargo/bin')];
  process.env.PATH = [...new Set([...(process.env.PATH || '').split(':'), ...extra])].filter(Boolean).join(':');
}

if (!app.requestSingleInstanceLock()) app.quit();

let win;
let store;
let bridge;
let hub;
let agent;

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

function startBridge(port) {
  bridge?.stop();
  bridge = new StudioBridge(port);
  bridge.mcpHandler = createMcpHandler({
    getTools: () => STUDIO_TOOLS.filter((t) => (store.getSettings().permissions[t.name] || defaultPermission(t.category)) !== 'off'),
    callTool: (name, args) => {
      if (!STUDIO_TOOL_NAMES.has(name)) throw new Error(`Unknown tool ${name}`);
      if (store.getSettings().permissions[name] === 'off') throw new Error(`${name} is turned off in Blox Bridge settings`);
      return bridge.call(name, args);
    },
  });
  bridge.on('status', (s) => send('studio:status', s));
  bridge.start();
  if (agent) agent.bridge = bridge;
}

function createWindow() {
  const mac = process.platform === 'darwin';
  win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 760,
    minHeight: 520,
    backgroundColor: '#1C1B19',
    title: 'Blox Bridge',
    titleBarStyle: mac ? 'hiddenInset' : 'hidden',
    titleBarOverlay: mac ? undefined : { color: '#161614', symbolColor: '#C9C5BC', height: 40 },
    trafficLightPosition: { x: 14, y: 13 },
    webPreferences: {
      preload: path.join(here, 'preload.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
    },
  });
  win.loadFile(path.join(here, '..', 'renderer', 'index.html'));
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('file:')) {
      e.preventDefault();
      if (/^https?:/.test(url)) shell.openExternal(url);
    }
  });
}

function registerIpc() {
  const h = (ch, fn) => ipcMain.handle(ch, (_e, ...args) => fn(...args));

  h('app:info', () => ({ version: app.getVersion(), platform: process.platform }));

  h('settings:get', () => store.getSettings());
  h('settings:set', (patch) => {
    const before = store.getSettings();
    const next = store.setSettings(patch || {});
    if (patch?.bridgePort && patch.bridgePort !== before.bridgePort) startBridge(next.bridgePort);
    if (patch?.mcpServers) hub.sync(next.mcpServers);
    return next;
  });

  h('models:detect', async () => {
    const providers = store.getSettings().providers;
    const results = await detectModels(providers);
    return providers.map((p) => ({ ...p, ...results.find((r) => r.providerId === p.id) }));
  });
  h('providers:add', ({ name, baseUrl, apiKey }) => {
    const s = store.getSettings();
    const p = { id: `custom-${randomUUID().slice(0, 8)}`, name: name || 'Custom', kind: 'openai', baseUrl, apiKey: apiKey || '' };
    store.setSettings({ providers: [...s.providers, p] });
    return p;
  });
  h('providers:remove', (id) => {
    const s = store.getSettings();
    store.setSettings({ providers: s.providers.filter((p) => p.id !== id || p.builtin) });
  });

  h('sessions:list', () => store.listSessions());
  h('sessions:get', (id) => {
    const s = store.getSession(id);
    return s && { ...s, running: agent.isRunning(id) };
  });
  h('sessions:create', () => store.createSession());
  h('sessions:rename', (id, title) => store.renameSession(id, title));
  h('sessions:delete', (id) => {
    agent.stop(id);
    store.deleteSession(id);
  });

  h('chat:send', (id, text) => {
    agent.send(id, text); // streams progress through chat:event
  });
  h('chat:stop', (id) => agent.stop(id));
  h('permission:respond', (requestId, decision) => agent.respondPermission(requestId, decision));

  h('tools:list', () =>
    agent.allTools().map(({ name, description, category, permission, server, source }) => ({
      name, description, category, permission, server, source,
    })));

  h('studio:status', () => ({ ...bridge.status(), plugin: pluginStatus() }));
  h('studio:installPlugin', () => {
    try {
      const file = installPlugin(store.getSettings().bridgePort);
      return { file, plugin: pluginStatus() };
    } catch (e) {
      if (process.platform === 'darwin' && (e.code === 'EPERM' || e.code === 'EACCES')) {
        throw new Error('macOS blocked access to your Documents folder. Allow Blox Bridge in System Settings › Privacy & Security › Files and Folders, or use "Save plugin file…".');
      }
      throw e;
    }
  });
  h('studio:openPluginsFolder', async () => {
    const folder = pluginsFolder();
    if (folder) await shell.openPath(folder);
  });
  h('studio:savePluginAs', async () => {
    const r = await dialog.showSaveDialog(win, { defaultPath: PLUGIN_FILE, filters: [{ name: 'Luau', extensions: ['lua'] }] });
    if (r.canceled || !r.filePath) return null;
    return writePluginTo(r.filePath, store.getSettings().bridgePort);
  });

  h('mcp:status', () => hub.status());
  h('clipboard:write', (text) => clipboard.writeText(String(text ?? '')));
  h('shell:open', (url) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
  });
}

app.whenReady().then(() => {
  store = new Store(app.getPath('userData'));
  hub = new McpHub();
  hub.on('status', (s) => send('mcp:status', s));
  startBridge(store.getSettings().bridgePort);
  agent = new Agent({ store, bridge, hub, emit: (sessionId, ev) => send('chat:event', { sessionId, ...ev }) });
  registerIpc();
  hub.sync(store.getSettings().mcpServers || []);
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('second-instance', () => {
  if (win) {
    if (win.isMinimized()) win.restore();
    win.focus();
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  bridge?.stop();
  hub?.closeAll();
});
