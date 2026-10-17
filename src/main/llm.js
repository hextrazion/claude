// Chat clients for local model servers.
//   kind "ollama": Ollama's native /api/chat (lets us set the context length)
//   kind "openai": any OpenAI-compatible server (LM Studio, llama.cpp, Jan, vLLM...)

import { randomUUID } from 'node:crypto';

const DETECT_TIMEOUT_MS = 1500;

export async function detectModels(providers) {
  const results = await Promise.all(providers.map((p) => listProviderModels(p)));
  return results;
}

async function listProviderModels(p) {
  try {
    if (p.kind === 'ollama') {
      const root = ollamaRoot(p.baseUrl);
      const tags = await getJson(`${root}/api/tags`, DETECT_TIMEOUT_MS);
      const models = await Promise.all((tags.models || []).map(async (m) => {
        let tools = null;
        try {
          const show = await postJson(`${root}/api/show`, { model: m.name }, 3000);
          if (Array.isArray(show.capabilities)) tools = show.capabilities.includes('tools');
        } catch {}
        return {
          id: m.name,
          size: m.size || null,
          params: m.details?.parameter_size || null,
          quant: m.details?.quantization_level || null,
          tools,
        };
      }));
      return { providerId: p.id, online: true, models };
    }
    const headers = p.apiKey ? { Authorization: `Bearer ${p.apiKey}` } : {};
    const list = await getJson(`${trimSlash(p.baseUrl)}/models`, DETECT_TIMEOUT_MS, headers);
    const models = (list.data || [])
      .filter((m) => !/embed/i.test(m.id))
      .map((m) => ({ id: m.id, size: null, params: null, quant: null, tools: null }));
    return { providerId: p.id, online: true, models };
  } catch (e) {
    return { providerId: p.id, online: false, models: [], error: String(e?.message || e) };
  }
}

// Streams one assistant turn. Calls onUpdate({ content, reasoning }) with the
// full text so far, and resolves with { content, reasoning, toolCalls }.
export async function chat({ provider, model, messages, tools, signal, onUpdate, options = {} }) {
  const fn = provider.kind === 'ollama' ? chatOllama : chatOpenAI;
  try {
    return await fn({ provider, model, messages, tools, signal, onUpdate, options });
  } catch (e) {
    if (e?.name === 'AbortError') throw e;
    throw new Error(friendlyError(e, provider, model));
  }
}

async function chatOllama({ provider, model, messages, tools, signal, onUpdate, options }) {
  const body = {
    model,
    stream: true,
    messages: messages.map(toOllamaMessage),
    options: { num_ctx: options.contextLength || 16384, temperature: options.temperature ?? 0.2 },
  };
  if (tools.length) body.tools = tools.map(toFunctionTool);
  const res = await fetch(`${ollamaRoot(provider.baseUrl)}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(await errorText(res));

  const acc = new Accumulator(onUpdate);
  const toolCalls = [];
  for await (const line of readLines(res.body)) {
    if (!line.trim()) continue;
    const chunk = JSON.parse(line);
    if (chunk.error) throw new Error(chunk.error);
    const m = chunk.message || {};
    if (m.thinking) acc.addReasoning(m.thinking);
    if (m.content) acc.addContent(m.content);
    for (const tc of m.tool_calls || []) {
      toolCalls.push({
        id: `call_${randomUUID().slice(0, 8)}`,
        type: 'function',
        function: {
          name: tc.function?.name,
          arguments: typeof tc.function?.arguments === 'string'
            ? tc.function.arguments
            : JSON.stringify(tc.function?.arguments || {}),
        },
      });
    }
  }
  return { ...acc.result(), toolCalls };
}

async function chatOpenAI({ provider, model, messages, tools, signal, onUpdate, options }) {
  const body = {
    model,
    stream: true,
    temperature: options.temperature ?? 0.2,
    messages: messages.map(toOpenAIMessage),
  };
  if (tools.length) body.tools = tools.map(toFunctionTool);
  const headers = { 'Content-Type': 'application/json' };
  if (provider.apiKey) headers.Authorization = `Bearer ${provider.apiKey}`;
  const res = await fetch(`${trimSlash(provider.baseUrl)}/chat/completions`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(await errorText(res));

  const acc = new Accumulator(onUpdate);
  const calls = [];
  for await (const line of readLines(res.body)) {
    const t = line.trim();
    if (!t.startsWith('data:')) continue;
    const data = t.slice(5).trim();
    if (data === '[DONE]') break;
    const chunk = JSON.parse(data);
    if (chunk.error) throw new Error(chunk.error.message || JSON.stringify(chunk.error));
    const d = chunk.choices?.[0]?.delta || {};
    const r = d.reasoning_content ?? d.reasoning;
    if (r) acc.addReasoning(r);
    if (d.content) acc.addContent(d.content);
    for (const tc of d.tool_calls || []) {
      const i = tc.index ?? calls.length;
      calls[i] ||= { id: tc.id || `call_${randomUUID().slice(0, 8)}`, type: 'function', function: { name: '', arguments: '' } };
      if (tc.id) calls[i].id = tc.id;
      if (tc.function?.name) calls[i].function.name += tc.function.name;
      if (tc.function?.arguments) calls[i].function.arguments += tc.function.arguments;
    }
  }
  return { ...acc.result(), toolCalls: calls.filter(Boolean) };
}

// Collects streamed text, splitting <think>...</think> blocks into reasoning.
class Accumulator {
  constructor(onUpdate) {
    this.raw = '';
    this.reasoning = '';
    this.onUpdate = onUpdate;
    this.lastEmit = 0;
  }
  addContent(t) {
    this.raw += t;
    this.emit();
  }
  addReasoning(t) {
    this.reasoning += t;
    this.emit();
  }
  emit() {
    const now = Date.now();
    if (now - this.lastEmit < 40) return;
    this.lastEmit = now;
    this.onUpdate?.(this.result());
  }
  result() {
    const { content, thinking } = splitThink(this.raw);
    return { content, reasoning: (this.reasoning + thinking).trim() };
  }
}

export function splitThink(raw) {
  let content = '';
  let thinking = '';
  let rest = raw;
  while (rest.length) {
    const open = rest.indexOf('<think>');
    if (open === -1) {
      content += rest;
      break;
    }
    content += rest.slice(0, open);
    const close = rest.indexOf('</think>', open);
    if (close === -1) {
      thinking += rest.slice(open + 7);
      break;
    }
    thinking += rest.slice(open + 7, close);
    rest = rest.slice(close + 8);
  }
  return { content: content.replace(/^\s+/, ''), thinking: thinking.trim() };
}

function toFunctionTool(t) {
  return { type: 'function', function: { name: t.name, description: t.description, parameters: t.parameters } };
}

function toOpenAIMessage(m) {
  if (m.role === 'assistant') {
    const out = { role: 'assistant', content: m.content || '' };
    if (m.tool_calls?.length) out.tool_calls = m.tool_calls;
    return out;
  }
  if (m.role === 'tool') return { role: 'tool', tool_call_id: m.tool_call_id, content: m.content };
  return { role: m.role, content: m.content };
}

function toOllamaMessage(m) {
  if (m.role === 'assistant') {
    const out = { role: 'assistant', content: m.content || '' };
    if (m.tool_calls?.length) {
      out.tool_calls = m.tool_calls.map((tc) => ({
        function: { name: tc.function.name, arguments: parseArgs(tc.function.arguments) },
      }));
    }
    return out;
  }
  if (m.role === 'tool') return { role: 'tool', content: m.content, tool_name: m.name };
  return { role: m.role, content: m.content };
}

export function parseArgs(s) {
  if (s && typeof s === 'object') return s;
  if (!s) return {};
  try {
    return JSON.parse(s);
  } catch {
    // Small models sometimes wrap JSON in code fences or add trailing text.
    const m = String(s).match(/\{[\s\S]*\}/);
    if (m) {
      try {
        return JSON.parse(m[0]);
      } catch {}
    }
    return {};
  }
}

function friendlyError(e, provider, model) {
  const msg = String(e?.message || e);
  if (/does not support tools|tool.*not supported|tools? (is|are) not supported/i.test(msg)) {
    return `${model} can't call tools, so it can't control Studio. Pick a model marked "Tools" (for example qwen2.5-coder, qwen3, llama3.1 or mistral-nemo).`;
  }
  if (/fetch failed|ECONNREFUSED|ENOTFOUND/i.test(msg) || e?.cause?.code === 'ECONNREFUSED') {
    return `Can't reach ${provider.name} at ${provider.baseUrl}. Make sure it is running${provider.kind === 'ollama' ? ' (open the Ollama app or run "ollama serve")' : ' and its local server is started'}.`;
  }
  if (/not found|no such model|model .* not/i.test(msg)) {
    return `${provider.name} doesn't have "${model}" loaded. ${msg}`;
  }
  return `${provider.name}: ${msg}`;
}

async function* readLines(stream) {
  const decoder = new TextDecoder();
  let buf = '';
  for await (const chunk of stream) {
    buf += decoder.decode(chunk, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) !== -1) {
      yield buf.slice(0, i);
      buf = buf.slice(i + 1);
    }
  }
  buf += decoder.decode();
  if (buf) yield buf;
}

async function getJson(url, timeoutMs, headers = {}) {
  const res = await fetch(url, { headers, signal: AbortSignal.timeout(timeoutMs) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function postJson(url, body, timeoutMs) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function errorText(res) {
  const text = await res.text().catch(() => '');
  try {
    const j = JSON.parse(text);
    return j.error?.message || j.error || j.message || text || `HTTP ${res.status}`;
  } catch {
    return text || `HTTP ${res.status}`;
  }
}

function ollamaRoot(url) {
  return trimSlash(url).replace(/\/v1$/, '');
}

function trimSlash(s) {
  return String(s || '').replace(/\/+$/, '');
}
