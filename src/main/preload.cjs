const { contextBridge, ipcRenderer } = require('electron');

const EVENTS = new Set(['chat:event', 'studio:status', 'mcp:status']);

contextBridge.exposeInMainWorld('api', {
  invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),
  on: (channel, fn) => {
    if (!EVENTS.has(channel)) throw new Error(`Unknown event ${channel}`);
    const handler = (_e, payload) => fn(payload);
    ipcRenderer.on(channel, handler);
    return () => ipcRenderer.removeListener(channel, handler);
  },
  platform: process.platform,
});
