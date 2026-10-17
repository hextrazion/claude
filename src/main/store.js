import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export const DEFAULT_PROVIDERS = [
  { id: 'ollama', name: 'Ollama', kind: 'ollama', baseUrl: 'http://127.0.0.1:11434', builtin: true },
  { id: 'lmstudio', name: 'LM Studio', kind: 'openai', baseUrl: 'http://127.0.0.1:1234/v1', builtin: true },
  { id: 'llamacpp', name: 'llama.cpp', kind: 'openai', baseUrl: 'http://127.0.0.1:8080/v1', builtin: true },
  { id: 'jan', name: 'Jan', kind: 'openai', baseUrl: 'http://127.0.0.1:1337/v1', builtin: true },
];

const DEFAULT_SETTINGS = {
  onboarded: false,
  providers: DEFAULT_PROVIDERS,
  model: null, // { providerId, id }
  mode: 'ask', // ask | auto | readonly
  permissions: {}, // toolName -> allow | ask | off
  mcpServers: [], // { id, name, type: stdio|http, command, args, url, enabled }
  bridgePort: 44755,
  contextLength: 16384,
  temperature: 0.2,
};

export class Store {
  constructor(dir) {
    this.dir = dir;
    this.sessionsDir = path.join(dir, 'sessions');
    fs.mkdirSync(this.sessionsDir, { recursive: true });
    this.settingsFile = path.join(dir, 'settings.json');
    this.settings = { ...DEFAULT_SETTINGS, ...readJson(this.settingsFile, {}) };
    // Keep built-in providers present even if an older settings file lacks them.
    for (const p of DEFAULT_PROVIDERS) {
      if (!this.settings.providers.some((x) => x.id === p.id)) this.settings.providers.push(p);
    }
    this.sessions = new Map();
    for (const f of fs.readdirSync(this.sessionsDir)) {
      if (!f.endsWith('.json')) continue;
      const s = readJson(path.join(this.sessionsDir, f), null);
      if (s && s.id) this.sessions.set(s.id, s);
    }
  }

  getSettings() {
    return this.settings;
  }

  setSettings(patch) {
    this.settings = { ...this.settings, ...patch };
    writeJson(this.settingsFile, this.settings);
    return this.settings;
  }

  listSessions() {
    return [...this.sessions.values()]
      .map(({ id, title, updatedAt }) => ({ id, title, updatedAt }))
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  getSession(id) {
    return this.sessions.get(id) || null;
  }

  createSession() {
    const now = Date.now();
    const s = { id: randomUUID(), title: 'New session', createdAt: now, updatedAt: now, messages: [] };
    this.sessions.set(s.id, s);
    this.saveSession(s);
    return s;
  }

  saveSession(s) {
    s.updatedAt = Date.now();
    writeJson(path.join(this.sessionsDir, `${s.id}.json`), s);
  }

  renameSession(id, title) {
    const s = this.sessions.get(id);
    if (!s) return;
    s.title = title;
    this.saveSession(s);
  }

  deleteSession(id) {
    this.sessions.delete(id);
    fs.rmSync(path.join(this.sessionsDir, `${id}.json`), { force: true });
  }
}

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function writeJson(file, data) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file);
}
