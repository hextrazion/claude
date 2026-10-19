// Local HTTP bridge between the app and the Roblox Studio plugin.
//
// The plugin long-polls GET /poll for the next command and POSTs the outcome
// to /result. The same server exposes the Studio tools as an MCP endpoint at
// /mcp so other MCP clients can drive Studio through the app too.
//
// Only loopback requests from non-browser clients are accepted: requests with
// an Origin header or a foreign Host are refused (blocks CSRF and DNS
// rebinding), and the plugin endpoints also require the X-Blox-Bridge header,
// which a web page cannot send cross-origin without a preflight we never pass.

import http from 'node:http';
import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';

const POLL_HOLD_MS = 15000;
const STALE_MS = 6000;

export class StudioBridge extends EventEmitter {
  constructor(port) {
    super();
    this.port = port;
    this.queue = [];
    this.pending = new Map();
    this.dispatched = new Set();
    this.waiter = null;
    this.lastSeen = 0;
    this.place = null;
    this.error = null;
    this.mcpHandler = null;
    this._last = '';
  }

  start() {
    this.server = http.createServer((req, res) => this.handle(req, res).catch((e) => {
      if (!res.headersSent) send(res, 500, { error: String(e?.message || e) });
    }));
    this.server.on('error', (e) => {
      this.error = e.code === 'EADDRINUSE'
        ? `Port ${this.port} is already in use. Close the other app using it or change the port in Settings.`
        : String(e.message || e);
      this.emitStatus(true);
    });
    this.server.listen(this.port, '127.0.0.1', () => {
      this.error = null;
      this.emitStatus(true);
    });
    this.timer = setInterval(() => this.emitStatus(), 1500);
  }

  stop() {
    clearInterval(this.timer);
    if (this.waiter) {
      clearTimeout(this.waiter.timer);
      this.waiter.res.writeHead(204).end();
      this.waiter = null;
    }
    this.server?.close();
  }

  get connected() {
    // A command being executed counts as connected: the plugin isn't polling then.
    return !!this.waiter || this.dispatched.size > 0 || Date.now() - this.lastSeen < STALE_MS;
  }

  status() {
    return {
      connected: this.connected,
      place: this.place,
      port: this.port,
      error: this.error,
      pluginVersion: this.pluginVersion || null,
      everSeen: !!this.everSeen,
    };
  }

  emitStatus(force = false) {
    const s = this.status();
    const key = JSON.stringify(s);
    if (force || key !== this._last) {
      this._last = key;
      this.emit('status', s);
    }
  }

  // Send a tool call to Studio and wait for the plugin's answer.
  call(tool, args, timeoutMs = 120000) {
    if (!this.connected) {
      return Promise.reject(new Error('Roblox Studio is not connected. Open Studio and click Plugins › Blox Bridge › Connect.'));
    }
    const id = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        this.dispatched.delete(id);
        this.queue = this.queue.filter((c) => c.id !== id);
        reject(new Error(`Studio did not answer ${tool} within ${Math.round(timeoutMs / 1000)}s.`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.queue.push({ id, tool, args: args || {} });
      this.flush();
    });
  }

  flush() {
    if (!this.waiter || !this.queue.length) return;
    const { res, timer } = this.waiter;
    this.waiter = null;
    clearTimeout(timer);
    const cmd = this.queue.shift();
    this.dispatched.add(cmd.id);
    send(res, 200, cmd);
  }

  async handle(req, res) {
    const url = new URL(req.url, 'http://127.0.0.1');
    const host = (req.headers.host || '').toLowerCase();
    if (req.headers.origin || !(host === `127.0.0.1:${this.port}` || host === `localhost:${this.port}`)) {
      return send(res, 403, { error: 'Forbidden' });
    }

    if (url.pathname === '/mcp') {
      if (!this.mcpHandler) return send(res, 503, { error: 'MCP not ready' });
      const body = req.method === 'POST' ? await readJsonBody(req) : undefined;
      return this.mcpHandler(req, res, body);
    }

    if (req.headers['x-blox-bridge'] !== '1') return send(res, 403, { error: 'Forbidden' });

    const place = req.headers['x-blox-place'];
    if (place) this.place = safeDecode(place);
    this.pluginVersion = req.headers['x-blox-plugin'] || '0.1.0';
    this.everSeen = true;
    this.lastSeen = Date.now();

    if (req.method === 'GET' && url.pathname === '/hello') {
      return send(res, 200, { app: 'blox-bridge', ok: true });
    }

    if (req.method === 'GET' && url.pathname === '/poll') {
      if (this.waiter) {
        clearTimeout(this.waiter.timer);
        this.waiter.res.writeHead(204).end();
      }
      const waiter = {
        res,
        timer: setTimeout(() => {
          if (this.waiter === waiter) this.waiter = null;
          this.lastSeen = Date.now();
          res.writeHead(204).end();
        }, POLL_HOLD_MS),
      };
      this.waiter = waiter;
      req.on('close', () => {
        if (this.waiter === waiter) {
          clearTimeout(waiter.timer);
          this.waiter = null;
          this.lastSeen = Date.now();
        }
      });
      this.emitStatus();
      return this.flush();
    }

    if (req.method === 'POST' && url.pathname === '/result') {
      const body = await readJsonBody(req);
      const p = this.pending.get(body?.id);
      this.dispatched.delete(body?.id);
      if (p) {
        clearTimeout(p.timer);
        this.pending.delete(body.id);
        if (body.ok) p.resolve(body.result ?? null);
        else p.reject(new Error(body.error || 'Studio reported an error'));
      }
      return send(res, 200, { ok: true });
    }

    send(res, 404, { error: 'Not found' });
  }
}

function send(res, code, obj) {
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.setEncoding('utf8');
    req.on('data', (c) => {
      data += c;
      if (data.length > 20 * 1024 * 1024) req.destroy();
    });
    req.on('end', () => {
      if (!data) return resolve(undefined);
      try {
        resolve(JSON.parse(data));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function safeDecode(s) {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}
