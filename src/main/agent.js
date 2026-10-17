// The agent loop: model turn -> tool calls (with permission prompts) -> repeat.

import { randomUUID } from 'node:crypto';
import { chat, parseArgs } from './llm.js';
import { STUDIO_TOOLS, SYSTEM_PROMPT, defaultPermission } from './tools.js';

const MAX_STEPS = 30;
const MAX_RESULT_CHARS = 16000;

export class Agent {
  constructor({ store, bridge, hub, emit }) {
    this.store = store;
    this.bridge = bridge;
    this.hub = hub;
    this.emit = emit; // (sessionId, event) => void
    this.running = new Map(); // sessionId -> AbortController
    this.permissionWaiters = new Map(); // requestId -> { resolve, sessionId }
  }

  // Every tool the app knows about, with its effective permission.
  allTools() {
    const perms = this.store.getSettings().permissions || {};
    const studio = STUDIO_TOOLS.map((t) => ({ ...t, source: 'studio', server: 'Roblox Studio' }));
    const external = this.hub.tools().map((t) => ({ ...t, source: 'mcp' }));
    return [...studio, ...external].map((t) => ({
      ...t,
      permission: perms[t.name] || defaultPermission(t.category),
    }));
  }

  // Tools offered to the model for this turn, given the session mode.
  activeTools() {
    const mode = this.store.getSettings().mode;
    return this.allTools().filter((t) => {
      if (t.permission === 'off') return false;
      if (mode === 'readonly' && t.category !== 'read') return false;
      return true;
    });
  }

  isRunning(sessionId) {
    return this.running.has(sessionId);
  }

  stop(sessionId) {
    this.running.get(sessionId)?.abort();
    for (const [id, w] of this.permissionWaiters) {
      if (w.sessionId === sessionId) {
        w.resolve('deny');
        this.permissionWaiters.delete(id);
      }
    }
  }

  respondPermission(requestId, decision) {
    const w = this.permissionWaiters.get(requestId);
    if (!w) return;
    this.permissionWaiters.delete(requestId);
    w.resolve(decision);
  }

  async send(sessionId, text) {
    const session = this.store.getSession(sessionId);
    if (!session || this.running.has(sessionId)) return;
    const settings = this.store.getSettings();
    const provider = settings.providers.find((p) => p.id === settings.model?.providerId);
    if (!provider || !settings.model?.id) {
      this.emit(sessionId, { type: 'error', message: 'Pick a model first (bottom right of the message box).' });
      return;
    }

    session.messages.push({ role: 'user', content: text });
    if (session.title === 'New session') session.title = text.replace(/\s+/g, ' ').slice(0, 60);
    this.store.saveSession(session);
    this.sync(session);

    const ctrl = new AbortController();
    this.running.set(sessionId, ctrl);
    this.emit(sessionId, { type: 'running', running: true });

    try {
      for (let step = 0; step < MAX_STEPS; step++) {
        const tools = this.activeTools();
        this.emit(sessionId, { type: 'stream', content: '', reasoning: '' });
        const out = await chat({
          provider,
          model: settings.model.id,
          messages: this.buildMessages(session),
          tools,
          signal: ctrl.signal,
          options: { contextLength: settings.contextLength, temperature: settings.temperature },
          onUpdate: (u) => this.emit(sessionId, { type: 'stream', ...u }),
        });
        const msg = { role: 'assistant', content: out.content, model: settings.model.id };
        if (out.reasoning) msg.reasoning = out.reasoning;
        if (out.toolCalls.length) msg.tool_calls = out.toolCalls;
        session.messages.push(msg);
        this.store.saveSession(session);
        this.sync(session);
        if (!out.toolCalls.length) break;

        for (const tc of out.toolCalls) {
          if (ctrl.signal.aborted) break;
          const result = await this.runTool(session, tc, tools, ctrl.signal);
          session.messages.push({
            role: 'tool',
            tool_call_id: tc.id,
            name: tc.function.name,
            content: result.content,
            status: result.status,
          });
          this.store.saveSession(session);
          this.sync(session);
        }
        if (ctrl.signal.aborted) break;
      }
    } catch (e) {
      if (e?.name !== 'AbortError') {
        session.messages.push({ role: 'error', content: String(e?.message || e) });
        this.store.saveSession(session);
      }
    } finally {
      this.running.delete(sessionId);
      this.sync(session);
      this.emit(sessionId, { type: 'running', running: false });
    }
  }

  async runTool(session, tc, tools, signal) {
    const name = tc.function.name;
    const tool = tools.find((t) => t.name === name);
    const args = parseArgs(tc.function.arguments);
    if (!tool) {
      return { status: 'error', content: `Unknown or disabled tool "${name}". Available: ${tools.map((t) => t.name).join(', ')}` };
    }

    const mode = this.store.getSettings().mode;
    let allowed = tool.permission === 'allow' || (mode === 'auto' && tool.category === 'write');
    if (!allowed) {
      const requestId = randomUUID();
      this.emit(session.id, {
        type: 'permission',
        requestId,
        toolCallId: tc.id,
        tool: name,
        server: tool.server,
        category: tool.category,
        args,
      });
      const decision = await new Promise((resolve) => {
        this.permissionWaiters.set(requestId, { resolve, sessionId: session.id });
        signal.addEventListener('abort', () => resolve('deny'), { once: true });
      });
      this.emit(session.id, { type: 'permission_done', requestId });
      if (decision === 'always') {
        const s = this.store.getSettings();
        this.store.setSettings({ permissions: { ...s.permissions, [name]: 'allow' } });
      }
      allowed = decision === 'once' || decision === 'always';
      if (!allowed) {
        return { status: 'denied', content: 'The user denied this tool call. Ask them how to proceed instead of retrying.' };
      }
    }

    this.emit(session.id, { type: 'tool_running', toolCallId: tc.id });
    try {
      const out = tool.source === 'studio' ? await this.bridge.call(name, args) : await this.hub.call(tool, args);
      let content = typeof out === 'string' ? out : JSON.stringify(out, null, 1);
      if (content.length > MAX_RESULT_CHARS) content = content.slice(0, MAX_RESULT_CHARS) + '\n…[truncated]';
      return { status: 'ok', content };
    } catch (e) {
      return { status: 'error', content: `Error: ${e?.message || e}` };
    }
  }

  buildMessages(session) {
    const studio = this.bridge.status();
    const ctx = studio.connected
      ? `Roblox Studio is connected${studio.place ? ` with place "${studio.place}" open` : ''}.`
      : 'Roblox Studio is NOT connected right now; Studio tools will fail until the user clicks Connect in the Blox Bridge plugin.';
    const msgs = [{ role: 'system', content: `${SYSTEM_PROMPT}\n\n${ctx}` }];
    for (const m of session.messages) {
      if (m.role === 'error') continue;
      msgs.push(m);
    }
    return msgs;
  }

  sync(session) {
    this.emit(session.id, { type: 'sync', session, running: this.running.has(session.id) });
  }
}
