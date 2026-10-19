// Blox Bridge renderer. Plain DOM + template strings, no framework.

const api = window.api;
const $ = (sel, root = document) => root.querySelector(sel);

const S = {
  view: 'chat', // chat | settings | onboarding
  settingsTab: 'models',
  settings: null,
  info: null,
  sessions: [],
  current: null,
  running: new Set(),
  stream: {}, // sessionId -> { content, reasoning }
  permissions: {}, // requestId -> event
  toolRunning: new Set(),
  expanded: new Set(),
  studio: { connected: false, place: null, port: 44755, error: null, plugin: { installed: false, folder: null } },
  providers: [],
  detecting: false,
  mcp: [],
  tools: [],
  sidebar: true,
  draft: '',
  form: {
    provName: '', provUrl: '', provKey: '',
    srvName: '', srvType: 'stdio', srvCommand: '', srvArgs: '', srvUrl: '',
  },
  popover: null, // { kind, anchor }
  toast: null,
};

/* ------------------------------------------------------------------ icons */

const ICONS = {
  logo: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  shield: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/>',
  shieldAlert: '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M12 9v4M12 16.5v.01"/>',
  bolt: '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3"/>',
  refresh: '<path d="M20 11a8 8 0 10-2.3 5.7M20 4v7h-7"/>',
  plug: '<path d="M9 2v6M15 2v6M7 8h10v4a5 5 0 01-10 0zM12 17v5"/>',
  folder: '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 012-2h9"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16v.01"/>',
  cube: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/>',
  tools: '<path d="M14.7 6.3a4 4 0 00-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 005.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
};

function icon(name, size = 16, extra = '') {
  // extra may override stroke / stroke-width; SVG keeps the first duplicate attribute, so skip the defaults then.
  const stroke = /\bstroke="/.test(extra) ? '' : 'stroke="currentColor"';
  const width = /stroke-width=/.test(extra) ? '' : 'stroke-width="1.9"';
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ${stroke} ${width} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${ICONS[name] || ''}</svg>`;
}

/* ---------------------------------------------------------------- helpers */

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

function md(src) {
  const blocks = [];
  src = String(src || '').replace(/```[^\n`]*\n?([\s\S]*?)(?:```|$)/g, (_, code) => {
    blocks.push(`<pre><code>${esc(code.replace(/\n$/, ''))}</code></pre>`);
    return `\n\u0000${blocks.length - 1}\u0000\n`;
  });
  const inline = (s) =>
    s.split(/(`[^`\n]+`)/g).map((p) => {
      if (/^`[^`]+`$/.test(p)) return `<code>${esc(p.slice(1, -1))}</code>`;
      let h = esc(p);
      h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      h = h.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<em>$2</em>');
      h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
      h = h.replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]);
      return h;
    }).join('');

  let html = '';
  let para = [];
  let list = null;
  const flushPara = () => {
    if (para.length) html += `<p>${inline(para.join('\n')).replace(/\n/g, '<br>')}</p>`;
    para = [];
  };
  const flushList = () => {
    if (list) html += `<${list.type}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.type}>`;
    list = null;
  };
  for (const line of src.split('\n')) {
    let m;
    if ((m = line.match(/^\u0000(\d+)\u0000$/))) {
      flushPara(); flushList();
      html += blocks[+m[1]];
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else if ((m = line.match(/^(#{1,4})\s+(.*)$/))) {
      flushPara(); flushList();
      html += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`;
    } else if ((m = line.match(/^\s*[-*+]\s+(.*)$/))) {
      flushPara();
      if (list?.type !== 'ul') { flushList(); list = { type: 'ul', items: [] }; }
      list.items.push(m[1]);
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      flushPara();
      if (list?.type !== 'ol') { flushList(); list = { type: 'ol', items: [] }; }
      list.items.push(m[1]);
    } else if ((m = line.match(/^>\s?(.*)$/))) {
      flushPara(); flushList();
      html += `<blockquote>${inline(m[1])}</blockquote>`;
    } else if (list && /^\s+/.test(line)) {
      list.items[list.items.length - 1] += ' ' + line.trim();
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return html;
}

function fmtSize(bytes) {
  if (!bytes) return '';
  return bytes > 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`;
}

const TOOL_HINT = /qwen|llama3\.[1-9]|llama-3\.[1-9]|llama4|mistral|mixtral|hermes|gpt-oss|granite|command-r|firefunction|functionary|devstral|glm|kimi|deepseek-v3/i;

function toolSupport(m) {
  if (m.tools === true) return 'yes';
  if (m.tools === false) return 'no';
  return TOOL_HINT.test(m.id) ? 'likely' : 'unknown';
}

function toolBadge(m) {
  const t = toolSupport(m);
  if (t === 'yes') return '<span class="badge ok">Tools</span>';
  if (t === 'likely') return '<span class="badge ok">Tools?</span>';
  if (t === 'no') return '<span class="badge bad">No tool calling</span>';
  return '';
}

function providerName(id) {
  return S.settings?.providers.find((p) => p.id === id)?.name || id;
}

function parseJson(s) {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function parseArgs(s) {
  if (s && typeof s === 'object') return s;
  return parseJson(s) || {};
}

const MODES = {
  ask: { label: 'Ask before edits', icon: 'shield', cls: '' },
  auto: { label: 'Auto-accept edits', icon: 'bolt', cls: 'mode-auto' },
  readonly: { label: 'Read only', icon: 'eye', cls: 'mode-readonly' },
};

function toast(text) {
  S.toast = text;
  renderToast();
  clearTimeout(toast.t);
  toast.t = setTimeout(() => {
    S.toast = null;
    renderToast();
  }, 2600);
}

/* ------------------------------------------------------------- sidebar */

function renderSidebar() {
  const model = S.settings.model;
  const studio = S.studio;
  const mcpConnected = S.mcp.filter((m) => m.state === 'connected').length;
  const studioDot = studio.error ? 'bad' : studio.connected ? 'ok' : 'warn pulse';
  return `
  <aside class="sidebar ${S.sidebar ? '' : 'collapsed'}">
    <div class="side-top drag">
      <div class="brand">
        <div class="logo">${icon('logo', 17, 'stroke="#1C1B19" stroke-width="2"')}</div>
        <span class="brand-name">Blox Bridge</span>
      </div>
      <span class="grow"></span>
      <button class="icon-btn" data-action="toggle-sidebar" aria-label="Hide sidebar">${icon('sidebar', 18)}</button>
    </div>
    <button class="btn new-session" data-action="new-session">
      ${icon('plus')}<span>New session</span><span class="kbd">${S.info?.platform === 'darwin' ? '⌘N' : 'Ctrl N'}</span>
    </button>
    <div class="section-label">Recent</div>
    <nav class="sessions" aria-label="Sessions">
      ${S.sessions.length ? S.sessions.map((s) => `
        <div class="session-item ${S.current?.id === s.id && S.view === 'chat' ? 'active' : ''}">
          <button class="open" data-action="open-session" data-id="${esc(s.id)}" title="${esc(s.title)}">${esc(s.title)}</button>
          ${S.running.has(s.id) ? '<span class="spinner" aria-label="Running"></span>' : ''}
          <button class="icon-btn" data-action="delete-session" data-id="${esc(s.id)}" aria-label="Delete session">${icon('trash', 15)}</button>
        </div>`).join('') : '<div class="empty-sessions">No sessions yet</div>'}
    </nav>
    <button class="connections" data-action="open-settings" data-arg="studio" aria-label="Connection status. Open settings">
      <div class="conn-row"><span class="dot ${model ? 'ok' : 'warn'}"></span><span class="k">Model</span><span class="v mono">${esc(model?.id || 'None picked')}</span></div>
      <div class="conn-row"><span class="dot ${studioDot}"></span><span class="k">Studio</span><span class="v">${esc(studio.error ? 'Bridge error' : studio.connected ? studio.place || 'Connected' : 'Waiting for Studio…')}</span></div>
      <div class="conn-row"><span class="dot ${S.mcp.some((m) => m.state === 'error') ? 'bad' : 'ok'}"></span><span class="k">MCP</span><span class="v mono">${S.tools.filter((t) => t.permission !== 'off').length} tools · :${esc(studio.port)}${mcpConnected ? ` · +${mcpConnected}` : ''}</span></div>
    </button>
    <button class="side-link ${S.view === 'settings' ? 'active' : ''}" data-action="open-settings">${icon('gear', 17)}Settings</button>
  </aside>`;
}

/* ---------------------------------------------------------------- chat */

function renderTopbar(title, sub) {
  const st = S.studio;
  const pill = st.error
    ? `<button class="pill bad" data-action="open-settings" data-arg="studio"><span class="dot bad"></span>Bridge error</button>`
    : st.connected
      ? `<button class="pill ok" data-action="open-settings" data-arg="studio"><span class="dot ok"></span>Studio connected</button>`
      : `<button class="pill" data-action="open-settings" data-arg="studio"><span class="dot warn pulse"></span>Studio not connected</button>`;
  return `
  <header class="topbar drag">
    ${S.sidebar ? '' : `<button class="icon-btn" data-action="toggle-sidebar" aria-label="Show sidebar">${icon('sidebar', 18)}</button>`}
    <div class="topbar-title">${esc(title)}${sub ? `<span class="sub">${esc(sub)}</span>` : ''}</div>
    ${pill}
  </header>`;
}

function argSummary(name, args) {
  if (!args || typeof args !== 'object') return '';
  if (name === 'create_instance') return `${args.class_name || ''}${args.name ? ` "${args.name}"` : ''} in ${args.parent || '?'}`;
  if (args.path) return args.path;
  if (args.code) return (args.code.split('\n').find((l) => l.trim()) || '').trim();
  if (args.query || args.class_name) return [args.query, args.class_name].filter(Boolean).join(' · ');
  if (Array.isArray(args.paths)) return args.paths.join(', ');
  const first = Object.values(args).find((v) => typeof v === 'string');
  return first || (Object.keys(args).length ? JSON.stringify(args) : '');
}

function resultSummary(name, status, content) {
  if (status === 'denied') return 'Denied';
  if (status === 'error') return 'Failed';
  const j = parseJson(content);
  if (!j) return '';
  switch (name) {
    case 'get_explorer_tree': return j.services ? `${j.services.length} services` : `${j.children_count ?? 0} children`;
    case 'find_instances': return `${j.count} found`;
    case 'read_script': return `${(j.source || '').split('\n').length} lines`;
    case 'write_script': return `${j.created ? 'new · ' : ''}${j.lines} lines`;
    case 'create_instance':
    case 'set_properties': return j.errors?.length ? `${j.errors.length} warning${j.errors.length > 1 ? 's' : ''}` : name === 'create_instance' ? 'created' : 'updated';
    case 'delete_instance': return 'deleted';
    case 'run_code': return j.output?.length ? `${j.output.length} line${j.output.length > 1 ? 's' : ''} printed` : 'ran';
    case 'get_output_log': return `${j.lines?.length || 0} lines`;
    case 'get_selection': return `${j.selection?.length || 0} selected`;
    default: return '';
  }
}

function prettyResult(content) {
  const j = parseJson(content);
  if (j && typeof j === 'object') {
    if (typeof j.source === 'string') return j.source;
    return JSON.stringify(j, null, 2);
  }
  return content || '';
}

function renderToolCall(tc, result, pendingPerm) {
  const name = tc.function?.name || '?';
  const args = parseArgs(tc.function?.arguments);
  const tool = S.tools.find((t) => t.name === name);
  const running = !result && S.toolRunning.has(tc.id);
  const status = result?.status;
  let ic;
  if (status === 'ok') ic = `<span class="ok-ic">${icon('check', 16, 'stroke="#6BC48A" stroke-width="2.3"')}</span>`;
  else if (status === 'error' || status === 'denied') ic = icon('x', 16, 'stroke="#E8857A" stroke-width="2.3"');
  else if (pendingPerm) ic = icon('shield', 16, 'stroke="#E58A4E"');
  else if (running || S.running.has(S.current?.id)) ic = '<span class="spinner"></span>';
  else ic = icon('x', 16, 'stroke="#8C887F"');

  const open = S.expanded.has(tc.id);
  let meta = result ? resultSummary(name, status, result.content) : pendingPerm ? 'Waiting for you' : running ? 'Running…' : '';
  let metaCls = '';
  if (name === 'write_script' && status === 'ok') metaCls = 'add';

  let input = '';
  if (args.source) input = args.source;
  else if (args.code) input = args.code;
  else if (Object.keys(args).length) input = JSON.stringify(args, null, 2);

  return `
  <div class="tool ${status === 'error' ? 'error' : ''}">
    <button class="tool-head" data-action="toggle-tool" data-id="${esc(tc.id)}" aria-expanded="${open}">
      ${ic}
      <span class="tool-name">${esc(name.includes('__') ? name.split('__').slice(1).join('__') : name)}</span>
      ${tool?.source === 'mcp' ? `<span class="tool-server">${esc(tool.server)}</span>` : ''}
      <span class="tool-arg">${esc(argSummary(name, args))}</span>
      <span class="tool-meta ${metaCls}">${esc(meta)}</span>
    </button>
    ${open ? `<div class="tool-body">
      ${input ? `<div class="label">Input</div><pre>${esc(input)}</pre>` : ''}
      ${result ? `<div class="label">${status === 'ok' ? 'Result' : status === 'denied' ? 'Denied' : 'Error'}</div><pre>${esc(prettyResult(result.content))}</pre>` : ''}
    </div>` : ''}
  </div>
  ${pendingPerm ? renderPermission(pendingPerm) : ''}`;
}

function renderPermission(p) {
  const verbs = {
    run_code: 'run code in Studio',
    write_script: 'write a script',
    create_instance: 'create an instance',
    set_properties: 'change properties',
    delete_instance: 'delete an instance',
  };
  const what = verbs[p.tool] || `use ${p.tool}${p.server && p.server !== 'Roblox Studio' ? ` (${p.server})` : ''}`;
  const a = p.args || {};
  let preview = a.code || a.source || JSON.stringify(a, null, 2);
  if (a.source && a.path) preview = `-- ${a.path}\n${a.source}`;
  return `
  <section class="perm" aria-label="Permission request">
    <div class="perm-title">${icon('shieldAlert', 18, 'stroke="#E58A4E"')}Allow the model to ${esc(what)}?</div>
    <pre>${esc(preview)}</pre>
    <div class="perm-actions">
      <button class="btn primary lg" data-action="perm" data-id="${esc(p.requestId)}" data-arg="once">Allow once</button>
      <button class="btn lg" data-action="perm" data-id="${esc(p.requestId)}" data-arg="always">Always allow ${esc(p.tool.length > 24 ? 'this tool' : p.tool)}</button>
      <button class="btn ghost lg" data-action="perm" data-id="${esc(p.requestId)}" data-arg="deny">Deny</button>
    </div>
    <div class="perm-hint">Enter to allow once · Esc to deny · Change defaults in Settings › Tools</div>
  </section>`;
}

function renderMessages(session) {
  const results = new Map();
  for (const m of session.messages) if (m.role === 'tool') results.set(m.tool_call_id, m);
  const perms = Object.values(S.permissions).filter((p) => p.sessionId === session.id);
  let html = '';
  for (const m of session.messages) {
    if (m.role === 'user') {
      html += `<div class="msg-user">${esc(m.content)}</div>`;
    } else if (m.role === 'assistant') {
      html += '<div class="msg-assistant">';
      if (m.reasoning) html += renderThinking(m.reasoning, false);
      if (m.content?.trim()) html += `<div class="md">${md(m.content)}</div>`;
      for (const tc of m.tool_calls || []) {
        html += renderToolCall(tc, results.get(tc.id), perms.find((p) => p.toolCallId === tc.id));
      }
      html += '</div>';
    } else if (m.role === 'error') {
      html += `<div class="err" role="alert">${icon('alert', 16)}<div>${esc(m.content)}</div></div>`;
    }
  }
  return html;
}

function renderThinking(text, live) {
  return `<details class="thinking" ${live ? 'open' : ''}><summary>${icon('chevron', 12)}${live ? 'Thinking…' : 'Thought'}</summary><div class="body">${esc(text)}</div></details>`;
}

function renderStream(sessionId) {
  const st = S.stream[sessionId];
  if (!S.running.has(sessionId)) return '';
  const hasPerm = Object.values(S.permissions).some((p) => p.sessionId === sessionId);
  if (hasPerm) return '';
  if (!st || (!st.content && !st.reasoning)) {
    return `<div class="working"><span class="spinner"></span>Working…</div>`;
  }
  return `<div class="msg-assistant">
    ${st.reasoning ? renderThinking(st.reasoning, !st.content) : ''}
    ${st.content ? `<div class="md caret">${md(st.content)}</div>` : ''}
  </div>`;
}

const STARTERS = [
  ['Explain my place', 'Look through my place and explain how it is organized and what each script does.'],
  ['Checkpoint system', 'Add an obby checkpoint system: touching a pad saves the player\'s stage and they respawn on their last pad.'],
  ['Day / night cycle', 'Add a smooth day/night cycle that loops every 10 minutes, with the lights in Workspace turning on at night.'],
  ['Find bugs', 'Read my scripts and find bugs or bad practices. Show me the worst ones first and offer fixes.'],
];

function renderChat() {
  const s = S.current;
  const empty = !s || !s.messages.length;
  const running = s && S.running.has(s.id);
  const mode = MODES[S.settings.mode] || MODES.ask;
  const model = S.settings.model;
  const studio = S.studio;
  return `
  <main class="main">
    ${renderTopbar(s?.title || 'New session', studio.connected && studio.place ? studio.place : '')}
    <div class="scroll" id="scroll">
      ${empty ? `
      <div class="welcome">
        <h1>What are we building?</h1>
        <p>${model ? `Using <span class="mono">${esc(model.id)}</span> on ${esc(providerName(model.providerId))}.` : 'Pick a model to get started.'} ${studio.connected ? 'Studio is connected, so the model can see and edit your place.' : 'Open Roblox Studio and the Blox Bridge plugin connects on its own.'}</p>
        <div class="starters">
          ${STARTERS.map(([t, p]) => `<button class="starter" data-action="starter" data-arg="${esc(p)}"><b>${esc(t)}</b>${esc(p.length > 70 ? p.slice(0, 68) + '…' : p)}</button>`).join('')}
        </div>
      </div>` : `
      <div class="thread" id="thread">
        ${renderMessages(s)}
        <div id="stream">${renderStream(s.id)}</div>
      </div>`}
    </div>
    <div class="composer-wrap">
      <div class="composer-inner">
        <div class="composer">
          <label for="prompt" class="sr">Message</label>
          <textarea id="prompt" rows="1" placeholder="${studio.connected ? 'Ask your model to build something in Studio…' : 'Ask anything. Connect Studio to let the model edit your place…'}">${esc(S.draft)}</textarea>
          <div class="composer-row">
            <button class="chip ${mode.cls}" data-action="mode-cycle" title="Shift+Tab to switch">${icon(mode.icon, 14)}${esc(mode.label)}</button>
            <span class="grow"></span>
            <button class="chip plain" data-action="model-menu" id="model-btn" aria-haspopup="menu" aria-label="Choose model">
              <span class="mono">${esc(model?.id || 'Pick a model')}</span>
              ${model ? `<span class="kbd">${esc(providerName(model.providerId))}</span>` : ''}
              ${icon('down', 12)}
            </button>
            ${running
              ? `<button class="send stop" data-action="stop" aria-label="Stop">${icon('stop', 16)}</button>`
              : `<button class="send" data-action="send" aria-label="Send" ${S.draft.trim() ? '' : 'disabled'}>${icon('up', 18, 'stroke-width="2.4"')}</button>`}
          </div>
        </div>
        <div class="composer-foot">Runs on your machine · ${studio.connected ? `Studio: ${esc(studio.place || 'connected')}` : 'Studio not connected'}</div>
      </div>
    </div>
  </main>`;
}

/* ------------------------------------------------------------ settings */

const TABS = [
  ['models', 'Models', 'cpu'],
  ['studio', 'Roblox Studio', 'cube'],
  ['tools', 'Tools & permissions', 'tools'],
  ['mcp', 'MCP servers', 'server'],
];

function renderSettings() {
  let body = '';
  if (S.settingsTab === 'models') body = renderModelsTab();
  else if (S.settingsTab === 'studio') body = renderStudioTab();
  else if (S.settingsTab === 'tools') body = renderToolsTab();
  else body = renderMcpTab();
  return `
  <main class="main">
    ${renderTopbar('Settings')}
    <div class="settings">
      <nav class="settings-nav" aria-label="Settings sections">
        ${TABS.map(([id, label, ic]) => `<button class="side-link ${S.settingsTab === id ? 'active' : ''}" data-action="settings-tab" data-arg="${id}">${icon(ic, 16)}${label}</button>`).join('')}
        <span class="grow"></span>
        <button class="side-link" data-action="close-settings">${icon('chevron', 16)}Back to chat</button>
      </nav>
      <div class="settings-body"><div class="settings-inner">${body}</div></div>
    </div>
  </main>`;
}

function renderModelList(selectAction) {
  const sel = S.settings.model;
  const online = S.providers.filter((p) => p.online && p.models?.length);
  const offline = S.providers.filter((p) => !p.online);
  const emptyOnline = S.providers.filter((p) => p.online && !p.models?.length);
  let html = '';
  if (S.detecting && !S.providers.length) return '<div class="working"><span class="spinner"></span>Looking for local models…</div>';
  for (const p of online) {
    html += `<div class="provider-label"><span class="dot ok"></span>${esc(p.name)} <span class="mono kbd">${esc(p.baseUrl)}</span></div>
    <div class="model-grid">
      ${p.models.map((m) => `
      <button class="model-card" data-action="${selectAction}" data-id="${esc(p.id)}" data-arg="${esc(m.id)}" aria-pressed="${sel?.providerId === p.id && sel?.id === m.id}">
        <span class="radio"></span>
        <span class="info"><span class="mono">${esc(m.id)}</span><span class="meta">${esc([m.params, m.quant, fmtSize(m.size)].filter(Boolean).join(' · ') || p.name)}</span></span>
        ${toolBadge(m)}
      </button>`).join('')}
    </div>`;
  }
  for (const p of emptyOnline) {
    html += `<div class="provider-label"><span class="dot warn"></span>${esc(p.name)} is running but has no models loaded.</div>`;
  }
  if (!online.length) {
    html += `<div class="status-box">${icon('alert', 18)}<div>No local models found. Install <a href="https://ollama.com/download" target="_blank">Ollama</a>, then run <code class="mono">ollama pull qwen2.5-coder:7b</code> in a terminal, and press Refresh. LM Studio, llama.cpp and Jan work too: start their local server.</div></div>`;
  }
  if (offline.length) {
    html += `<p class="help">Not running: ${offline.map((p) => esc(p.name)).join(', ')}</p>`;
  }
  return html;
}

function renderModelsTab() {
  const custom = S.settings.providers.filter((p) => !p.builtin);
  return `
  <div><h2>Models</h2><p class="lead">Blox Bridge finds models from local servers on this computer. Pick one that supports tool calling so it can control Studio.</p></div>
  <section class="card">
    <div class="card-head"><h3>Detected models</h3><button class="btn sm" data-action="refresh-models">${S.detecting ? '<span class="spinner"></span>' : icon('refresh', 14)}Refresh</button></div>
    <div class="card-body">${renderModelList('pick-model')}</div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Servers</h3></div>
    <div class="list">
      ${S.settings.providers.map((p) => {
        const d = S.providers.find((x) => x.id === p.id);
        return `<div class="list-row">
          <span class="dot ${d?.online ? 'ok' : ''}"></span>
          <div class="main-col"><div>${esc(p.name)} <span class="badge">${p.kind === 'ollama' ? 'Ollama API' : 'OpenAI-compatible'}</span></div></div>
          <div class="field"><label class="sr" for="url-${esc(p.id)}">Base URL for ${esc(p.name)}</label><input class="input mono" id="url-${esc(p.id)}" data-change="provider-url" data-id="${esc(p.id)}" value="${esc(p.baseUrl)}"></div>
          ${p.builtin ? '' : `<button class="icon-btn" data-action="remove-provider" data-id="${esc(p.id)}" aria-label="Remove ${esc(p.name)}">${icon('trash', 15)}</button>`}
        </div>`;
      }).join('')}
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Add an OpenAI-compatible endpoint</h3></div>
    <div class="card-body">
      <p class="help">vLLM, KoboldCpp, text-generation-webui, LocalAI, or a remote server. Use the URL that ends in /v1.</p>
      <div class="row">
        <div class="field"><label for="f-provName">Name</label><input class="input" id="f-provName" data-bind="provName" value="${esc(S.form.provName)}" placeholder="My server"></div>
        <div class="field"><label for="f-provUrl">Base URL</label><input class="input mono" id="f-provUrl" data-bind="provUrl" value="${esc(S.form.provUrl)}" placeholder="http://127.0.0.1:5000/v1"></div>
      </div>
      <div class="row">
        <div class="field"><label for="f-provKey">API key (optional)</label><input class="input mono" id="f-provKey" type="password" data-bind="provKey" value="${esc(S.form.provKey)}"></div>
        <button class="btn" data-action="add-provider">${icon('plus', 14)}Add</button>
      </div>
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Generation</h3></div>
    <div class="card-body">
      <div class="row">
        <div class="field"><label for="ctx">Context length (Ollama)</label>
          <select class="input" id="ctx" data-change="context">
            ${[8192, 16384, 32768, 65536, 131072].map((n) => `<option value="${n}" ${S.settings.contextLength === n ? 'selected' : ''}>${n.toLocaleString()} tokens</option>`).join('')}
          </select></div>
        <div class="field"><label for="temp">Temperature</label>
          <select class="input" id="temp" data-change="temperature">
            ${[0, 0.2, 0.4, 0.7, 1].map((n) => `<option value="${n}" ${S.settings.temperature === n ? 'selected' : ''}>${n}</option>`).join('')}
          </select></div>
      </div>
      <p class="help">Bigger context lets the model read more scripts but uses more memory. 16k is a good start for 7–14B models.</p>
    </div>
  </section>
  ${custom.length ? '' : ''}`;
}

function renderStudioTab() {
  const st = S.studio;
  const mcpUrl = `http://127.0.0.1:${st.port}/mcp`;
  const cfg = JSON.stringify({ mcpServers: { 'roblox-studio': { command: 'npx', args: ['-y', 'mcp-remote', mcpUrl] } } }, null, 2);
  return `
  <div><h2>Roblox Studio</h2><p class="lead">A small Studio plugin talks to this app over 127.0.0.1. Nothing goes over the internet.</p></div>
  <section class="card">
    <div class="card-head"><h3>Connection</h3></div>
    <div class="card-body">
      ${st.error
        ? `<div class="err">${icon('alert', 16)}<div>${esc(st.error)}</div></div>`
        : st.connected
          ? `<div class="status-box ok">${icon('check', 18)}<div>Connected to <b>${esc(st.place || 'Studio')}</b></div></div>`
          : `<div class="status-box"><span class="spinner"></span><div>Waiting for Studio on port ${esc(st.port)}…</div></div>`}
      ${renderStudioSteps()}
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Use Studio from other MCP apps</h3></div>
    <div class="card-body">
      <p class="help">While Blox Bridge is open, any MCP client can drive Studio through it. Streamable HTTP endpoint:</p>
      <div class="code-block"><pre id="mcp-url">${esc(mcpUrl)}</pre><button class="btn sm" data-action="copy" data-arg="mcp-url">${icon('copy', 13)}Copy</button></div>
      <p class="help">For clients that only speak stdio (e.g. Claude Desktop), add this to their config:</p>
      <div class="code-block"><pre id="mcp-cfg">${esc(cfg)}</pre><button class="btn sm" data-action="copy" data-arg="mcp-cfg">${icon('copy', 13)}Copy</button></div>
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Bridge port</h3></div>
    <div class="card-body">
      <div class="row">
        <div class="field"><label for="port">Port</label><input class="input mono" id="port" inputmode="numeric" data-change="port" value="${esc(S.settings.bridgePort)}"></div>
      </div>
      <p class="help">If you change it, click Install / update plugin again so the plugin uses the new port.</p>
    </div>
  </section>`;
}

function renderStudioSteps() {
  const st = S.studio;
  const pl = st.plugin || {};
  const canInstall = !!pl.folder;
  const mod = S.info?.platform === 'darwin' ? '⌘' : 'Ctrl+';
  return `
  <ol class="studio-steps">
    <li>${pl.installed ? `Plugin installed ✓${pl.installedVersion ? ` <span class="kbd">v${esc(pl.installedVersion)}</span>` : ''}` : 'Install the Blox Bridge plugin into Studio.'}</li>
    <li><b>Restart Roblox Studio</b> after installing or updating, then open your place.</li>
    <li>If Studio asks whether Blox Bridge may connect to 127.0.0.1, click <b>Allow</b>.</li>
    <li>It connects by itself. The <b>Plugins › Blox Bridge › Connect</b> button turns it on and off.</li>
  </ol>
  ${st.connected && st.pluginVersion && pl.latestVersion && !pl.outdated && st.pluginVersion !== pl.latestVersion ? `<div class="status-box">${icon('alert', 18)}<div>Studio is still running the old plugin (v${esc(st.pluginVersion)}). Restart Studio to load v${esc(pl.latestVersion)}.</div></div>` : ''}
  ${pl.outdated ? `<div class="status-box">${icon('alert', 18)}<div>Your Studio plugin is out of date (v${esc(pl.installedVersion)}, newest v${esc(pl.latestVersion)}). Click <b>Update plugin</b>, then restart Studio.</div></div>` : ''}
  <div class="row">
    ${canInstall ? `<button class="btn ${pl.installed && !pl.outdated ? '' : 'primary'}" data-action="install-plugin">${icon('download', 15)}${pl.installed ? 'Update plugin' : 'Install plugin'}</button>
    <button class="btn ghost" data-action="open-plugins-folder">${icon('folder', 15)}Open plugins folder</button>` : ''}
    <button class="btn ghost" data-action="save-plugin">${icon('download', 15)}Save plugin file…</button>
  </div>
  ${!st.connected && !st.error ? `
  <details class="trouble">
    <summary>${icon('chevron', 12)}Studio is open but not connecting?</summary>
    <ul>
      <li><b>Restart Studio completely</b> (${mod}Q, then reopen it). Studio only loads new plugins when it starts.</li>
      <li>In Studio open <b>View › Output</b>. Lines starting with <span class="mono">[Blox Bridge]</span> say exactly what's wrong. No lines at all means the plugin didn't load: click <b>Open plugins folder</b> and check <span class="mono">BloxBridge.lua</span> is there.</li>
      <li>Check the <b>Plugins</b> tab has a <b>Blox Bridge › Connect</b> button and that it's highlighted (on).</li>
      <li>If you clicked Deny when Studio asked about 127.0.0.1: <b>Plugins › Manage Plugins</b>, find Blox Bridge, and allow its HTTP access.</li>
      <li>Keep this app open. Studio connects to it, not the other way round.</li>
    </ul>
  </details>` : ''}`;
}

function renderToolsTab() {
  const groups = [
    ['Read', 'Look at your place. Safe.', (t) => t.source === 'studio' && t.category === 'read'],
    ['Edit', 'Change instances and scripts. Every change is one Ctrl+Z in Studio.', (t) => t.source === 'studio' && t.category === 'write'],
    ['Run', 'Run Luau with plugin permissions.', (t) => t.source === 'studio' && t.category === 'run'],
  ];
  const servers = [...new Set(S.tools.filter((t) => t.source === 'mcp').map((t) => t.server))];
  for (const srv of servers) groups.push([srv, 'From an MCP server you added.', (t) => t.source === 'mcp' && t.server === srv]);
  return `
  <div><h2>Tools & permissions</h2><p class="lead">What the model may do. <b>Ask</b> shows you each call first. <b>Off</b> hides the tool from the model.</p></div>
  ${groups.map(([title, desc, f]) => {
    const list = S.tools.filter(f);
    if (!list.length) return '';
    return `<section class="card">
      <div class="card-head"><h3>${esc(title)}</h3><span class="help">${esc(desc)}</span></div>
      <div class="list">${list.map((t) => `
        <div class="list-row">
          <div class="main-col"><div class="name">${esc(t.name.includes('__') ? t.name.split('__').slice(1).join('__') : t.name)}</div><div class="desc">${esc((t.description || '').split('. ')[0])}</div></div>
          <div class="seg" role="group" aria-label="Permission for ${esc(t.name)}">
            ${['allow', 'ask', 'off'].map((v) => `<button class="${v}" data-action="set-perm" data-id="${esc(t.name)}" data-arg="${v}" aria-pressed="${t.permission === v}">${v[0].toUpperCase() + v.slice(1)}</button>`).join('')}
          </div>
        </div>`).join('')}
      </div>
    </section>`;
  }).join('')}`;
}

function renderMcpTab() {
  const servers = S.settings.mcpServers || [];
  const f = S.form;
  return `
  <div><h2>MCP servers</h2><p class="lead">Give your model more tools: add any MCP server (stdio command or HTTP URL). Its tools show up next to the Studio tools.</p></div>
  <section class="card">
    <div class="card-head"><h3>Your servers</h3></div>
    <div class="list">
      ${servers.length ? servers.map((s) => {
        const st = S.mcp.find((m) => m.id === s.id);
        const state = s.enabled === false ? 'disabled' : st?.state || 'connecting';
        const dot = state === 'connected' ? 'ok' : state === 'error' ? 'bad' : state === 'disabled' ? '' : 'warn pulse';
        return `<div class="list-row">
          <span class="dot ${dot}"></span>
          <div class="main-col">
            <div>${esc(s.name)} <span class="badge">${s.type === 'http' ? 'HTTP' : 'stdio'}</span> ${state === 'connected' ? `<span class="badge ok">${st.tools.length} tools</span>` : ''}</div>
            <div class="desc mono">${esc(s.type === 'http' ? s.url : `${s.command} ${s.args || ''}`)}</div>
            ${state === 'error' ? `<div class="desc">${esc(st?.error || '')}</div>` : ''}
          </div>
          <button class="btn sm" data-action="toggle-server" data-id="${esc(s.id)}">${s.enabled === false ? 'Enable' : 'Disable'}</button>
          <button class="icon-btn" data-action="remove-server" data-id="${esc(s.id)}" aria-label="Remove ${esc(s.name)}">${icon('trash', 15)}</button>
        </div>`;
      }).join('') : '<div class="list-row"><span class="help">None yet. Roblox Studio is built in, so you don\'t need to add it.</span></div>'}
    </div>
  </section>
  <section class="card">
    <div class="card-head"><h3>Add a server</h3></div>
    <div class="card-body">
      <div class="row">
        <div class="field"><label for="f-srvName">Name</label><input class="input" id="f-srvName" data-bind="srvName" value="${esc(f.srvName)}" placeholder="filesystem"></div>
        <div class="field"><label for="f-srvType">Type</label>
          <select class="input" id="f-srvType" data-bind="srvType">
            <option value="stdio" ${f.srvType === 'stdio' ? 'selected' : ''}>Command (stdio)</option>
            <option value="http" ${f.srvType === 'http' ? 'selected' : ''}>URL (Streamable HTTP)</option>
          </select></div>
      </div>
      ${f.srvType === 'http'
        ? `<div class="field"><label for="f-srvUrl">URL</label><input class="input mono" id="f-srvUrl" data-bind="srvUrl" value="${esc(f.srvUrl)}" placeholder="http://127.0.0.1:3000/mcp"></div>`
        : `<div class="row">
            <div class="field"><label for="f-srvCommand">Command</label><input class="input mono" id="f-srvCommand" data-bind="srvCommand" value="${esc(f.srvCommand)}" placeholder="npx"></div>
            <div class="field"><label for="f-srvArgs">Arguments</label><input class="input mono" id="f-srvArgs" data-bind="srvArgs" value="${esc(f.srvArgs)}" placeholder="-y @modelcontextprotocol/server-filesystem C:/RobloxProjects"></div>
          </div>`}
      <div class="row"><button class="btn" data-action="add-server">${icon('plus', 14)}Add server</button></div>
    </div>
  </section>`;
}

/* ---------------------------------------------------------- onboarding */

function renderOnboarding() {
  const model = S.settings.model;
  const st = S.studio;
  return `
  <main class="main">
    <div class="onboard">
      <div class="onboard-top drag"></div>
      <div class="onboard-inner">
        <div class="brand">
          <div class="logo">${icon('logo', 17, 'stroke="#1C1B19" stroke-width="2"')}</div>
          <span class="brand-name">Blox Bridge</span>
        </div>
        <div>
          <h1>Connect a model to Roblox Studio</h1>
          <p class="lead">Two steps. Blox Bridge runs the MCP bridge for you.</p>
        </div>
        <section class="step">
          <div class="step-head">
            <span class="step-num ${model ? 'done' : ''}">${model ? icon('check', 14, 'stroke-width="3"') : '1'}</span>
            <h2>Pick a model</h2>
            <button class="btn sm" data-action="refresh-models">${S.detecting ? '<span class="spinner"></span>' : icon('refresh', 14)}Refresh</button>
          </div>
          <div class="step-body">${renderModelList('pick-model')}</div>
        </section>
        <section class="step">
          <div class="step-head">
            <span class="step-num ${st.connected ? 'done' : ''}">${st.connected ? icon('check', 14, 'stroke-width="3"') : '2'}</span>
            <h2>Connect Roblox Studio</h2>
          </div>
          <div class="step-body">
            ${renderStudioSteps()}
            ${st.error
              ? `<div class="err">${icon('alert', 16)}<div>${esc(st.error)}</div></div>`
              : st.connected
                ? `<div class="status-box ok">${icon('check', 18)}<div>Connected to <b>${esc(st.place || 'Studio')}</b></div></div>`
                : `<div class="status-box"><span class="spinner"></span><div>Waiting for Studio on 127.0.0.1:${esc(st.port)}…</div></div>`}
          </div>
        </section>
        <div class="onboard-foot">
          ${st.connected ? '' : '<span class="help">You can connect Studio later.</span>'}
          <button class="btn primary lg" data-action="onboard-finish" ${model ? '' : 'disabled'}>Start building</button>
        </div>
      </div>
    </div>
  </main>`;
}

/* -------------------------------------------------------------- popover */

function renderPopover() {
  const root = $('#popover-root');
  if (!S.popover) {
    root.innerHTML = '';
    return;
  }
  const sel = S.settings.model;
  let html = '<div class="popover" role="menu" id="popover">';
  const online = S.providers.filter((p) => p.online && p.models?.length);
  if (!online.length) html += `<div class="pop-empty">${S.detecting ? 'Looking for models…' : 'No local models found. Start Ollama or LM Studio, then Refresh.'}</div>`;
  for (const p of online) {
    html += `<div class="pop-group">${esc(p.name)}</div>`;
    for (const m of p.models) {
      const on = sel?.providerId === p.id && sel?.id === m.id;
      html += `<button class="pop-item" role="menuitemradio" aria-checked="${on}" data-action="pick-model" data-id="${esc(p.id)}" data-arg="${esc(m.id)}">
        <span class="check">${on ? icon('check', 15, 'stroke-width="2.4"') : ''}</span>
        <span class="mono">${esc(m.id)}</span>${toolBadge(m)}</button>`;
    }
  }
  html += `<div class="pop-sep"></div>
    <button class="pop-item" role="menuitem" data-action="refresh-models"><span class="check">${icon('refresh', 14)}</span>Refresh models</button>
    <button class="pop-item" role="menuitem" data-action="open-settings" data-arg="models"><span class="check">${icon('gear', 14)}</span>Model settings…</button>
  </div>`;
  root.innerHTML = html;
  const pop = $('#popover');
  const anchor = document.getElementById(S.popover.anchor);
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    const w = pop.offsetWidth;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w))}px`;
    pop.style.bottom = `${window.innerHeight - r.top + 6}px`;
  }
}

function renderToast() {
  let el = $('#toast');
  if (!S.toast) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    el.setAttribute('role', 'status');
    document.body.appendChild(el);
  }
  el.textContent = S.toast;
}

/* ---------------------------------------------------------------- render */

function render() {
  if (!S.settings) return;
  const app = $('#app');
  const active = document.activeElement;
  const focusId = active?.id;
  const selStart = active?.selectionStart;
  const selEnd = active?.selectionEnd;
  const scroller = $('#scroll');
  const nearBottom = scroller ? scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80 : true;
  const prevTop = scroller?.scrollTop || 0;
  const settingsScroll = $('.settings-body')?.scrollTop || 0;

  let main;
  if (S.view === 'onboarding') main = renderOnboarding();
  else if (S.view === 'settings') main = renderSettings();
  else main = renderChat();
  app.innerHTML = (S.view === 'onboarding' ? '' : renderSidebar()) + main;

  const sc = $('#scroll');
  if (sc) sc.scrollTop = nearBottom ? sc.scrollHeight : prevTop;
  const sb = $('.settings-body');
  if (sb) sb.scrollTop = settingsScroll;
  if (focusId) {
    const el = document.getElementById(focusId);
    if (el) {
      el.focus();
      if (selStart != null && el.setSelectionRange) {
        try { el.setSelectionRange(selStart, selEnd); } catch {}
      }
    }
  }
  autosize();
  renderPopover();
}

function renderStreamOnly() {
  const el = $('#stream');
  if (!el || !S.current) return render();
  const sc = $('#scroll');
  const nearBottom = sc ? sc.scrollHeight - sc.scrollTop - sc.clientHeight < 120 : true;
  el.innerHTML = renderStream(S.current.id);
  if (sc && nearBottom) sc.scrollTop = sc.scrollHeight;
}

function autosize() {
  const ta = $('#prompt');
  if (!ta) return;
  ta.style.height = 'auto';
  ta.style.height = `${Math.min(240, ta.scrollHeight)}px`;
}

/* --------------------------------------------------------------- actions */

async function refreshSessions() {
  S.sessions = await api.invoke('sessions:list');
}

async function refreshTools() {
  S.tools = await api.invoke('tools:list');
}

async function detect() {
  S.detecting = true;
  render();
  try {
    S.providers = await api.invoke('models:detect');
  } finally {
    S.detecting = false;
  }
  // Auto-pick a model if none is chosen yet: prefer one known to support tools.
  if (!S.settings.model) {
    const all = S.providers.flatMap((p) => (p.models || []).map((m) => ({ p, m })));
    const pick = all.find((x) => toolSupport(x.m) === 'yes') || all.find((x) => toolSupport(x.m) === 'likely') || all[0];
    if (pick) S.settings = await api.invoke('settings:set', { model: { providerId: pick.p.id, id: pick.m.id } });
  }
  render();
}

async function openSession(id) {
  S.current = await api.invoke('sessions:get', id);
  if (S.current?.running) S.running.add(id);
  S.view = 'chat';
  S.draft = '';
  render();
  $('#prompt')?.focus();
}

async function newSession() {
  if (S.current && !S.current.messages.length) {
    S.view = 'chat';
    render();
    $('#prompt')?.focus();
    return;
  }
  const s = await api.invoke('sessions:create');
  await refreshSessions();
  await openSession(s.id);
}

async function send(text) {
  text = (text ?? S.draft).trim();
  if (!text) return;
  if (!S.settings.model) {
    toast('Pick a model first');
    S.popover = { kind: 'model', anchor: 'model-btn' };
    render();
    return;
  }
  if (!S.current) {
    const s = await api.invoke('sessions:create');
    S.current = s;
  }
  if (S.running.has(S.current.id)) return;
  S.draft = '';
  S.running.add(S.current.id);
  S.current.messages.push({ role: 'user', content: text });
  render();
  api.invoke('chat:send', S.current.id, text);
}

function cycleMode() {
  const order = ['ask', 'auto', 'readonly'];
  const next = order[(order.indexOf(S.settings.mode) + 1) % order.length];
  api.invoke('settings:set', { mode: next }).then((s) => {
    S.settings = s;
    render();
  });
}

function respondPermission(requestId, decision) {
  const p = S.permissions[requestId];
  if (!p) return;
  delete S.permissions[requestId];
  if (decision !== 'deny') S.toolRunning.add(p.toolCallId);
  api.invoke('permission:respond', requestId, decision);
  if (decision === 'always') refreshTools();
  render();
}

async function saveSettings(patch) {
  S.settings = await api.invoke('settings:set', patch);
  render();
}

const actions = {
  'toggle-sidebar': () => { S.sidebar = !S.sidebar; render(); },
  'new-session': newSession,
  'open-session': (el) => openSession(el.dataset.id),
  'delete-session': async (el) => {
    await api.invoke('sessions:delete', el.dataset.id);
    if (S.current?.id === el.dataset.id) S.current = null;
    await refreshSessions();
    render();
  },
  'open-settings': async (el) => {
    S.popover = null;
    S.view = 'settings';
    if (el.dataset.arg) S.settingsTab = el.dataset.arg;
    await refreshTools();
    render();
  },
  'close-settings': () => { S.view = 'chat'; render(); },
  'settings-tab': async (el) => {
    S.settingsTab = el.dataset.arg;
    if (S.settingsTab === 'tools') await refreshTools();
    render();
  },
  send: () => send(),
  stop: () => S.current && api.invoke('chat:stop', S.current.id),
  starter: (el) => send(el.dataset.arg),
  'mode-cycle': cycleMode,
  'model-menu': () => {
    S.popover = S.popover ? null : { kind: 'model', anchor: 'model-btn' };
    if (S.popover && !S.providers.length) detect();
    renderPopover();
  },
  'pick-model': async (el) => {
    S.popover = null;
    await saveSettings({ model: { providerId: el.dataset.id, id: el.dataset.arg } });
  },
  'refresh-models': () => detect(),
  'toggle-tool': (el) => {
    const id = el.dataset.id;
    if (S.expanded.has(id)) S.expanded.delete(id);
    else S.expanded.add(id);
    render();
  },
  perm: (el) => respondPermission(el.dataset.id, el.dataset.arg),
  'install-plugin': async () => {
    try {
      const r = await api.invoke('studio:installPlugin');
      S.studio.plugin = r.plugin;
      toast('Plugin installed. Restart Studio if it was open.');
    } catch (e) {
      toast(String(e.message || e).replace(/^Error invoking remote method '[^']+': (Error: )?/, ''));
    }
    render();
  },
  'open-plugins-folder': () => api.invoke('studio:openPluginsFolder'),
  'save-plugin': async () => {
    const f = await api.invoke('studio:savePluginAs');
    if (f) toast('Saved. Put it in your Studio Plugins folder.');
  },
  'set-perm': async (el) => {
    await saveSettings({ permissions: { ...S.settings.permissions, [el.dataset.id]: el.dataset.arg } });
    await refreshTools();
    render();
  },
  'add-provider': async () => {
    const { provName, provUrl, provKey } = S.form;
    if (!/^https?:\/\//.test(provUrl.trim())) return toast('Enter a URL starting with http:// or https://');
    await api.invoke('providers:add', { name: provName.trim() || 'Custom', baseUrl: provUrl.trim(), apiKey: provKey });
    S.form.provName = S.form.provUrl = S.form.provKey = '';
    S.settings = await api.invoke('settings:get');
    detect();
  },
  'remove-provider': async (el) => {
    await api.invoke('providers:remove', el.dataset.id);
    S.settings = await api.invoke('settings:get');
    detect();
  },
  'add-server': async () => {
    const f = S.form;
    const name = f.srvName.trim() || (f.srvType === 'http' ? 'http-server' : f.srvCommand.trim());
    if (f.srvType === 'http' ? !/^https?:\/\//.test(f.srvUrl.trim()) : !f.srvCommand.trim()) {
      return toast(f.srvType === 'http' ? 'Enter the server URL' : 'Enter a command, e.g. npx');
    }
    const server = {
      id: `srv-${Math.random().toString(36).slice(2, 10)}`,
      name,
      type: f.srvType,
      command: f.srvCommand.trim(),
      args: f.srvArgs.trim(),
      url: f.srvUrl.trim(),
      enabled: true,
    };
    S.form.srvName = S.form.srvCommand = S.form.srvArgs = S.form.srvUrl = '';
    await saveSettings({ mcpServers: [...(S.settings.mcpServers || []), server] });
  },
  'remove-server': async (el) => {
    await saveSettings({ mcpServers: S.settings.mcpServers.filter((s) => s.id !== el.dataset.id) });
  },
  'toggle-server': async (el) => {
    await saveSettings({
      mcpServers: S.settings.mcpServers.map((s) => (s.id === el.dataset.id ? { ...s, enabled: s.enabled === false } : s)),
    });
  },
  copy: async (el) => {
    const text = document.getElementById(el.dataset.arg)?.textContent || '';
    await api.invoke('clipboard:write', text);
    toast('Copied');
  },
  'onboard-finish': async () => {
    await saveSettings({ onboarded: true });
    S.view = 'chat';
    await newSession();
  },
};

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (S.popover && !e.target.closest('#popover') && el?.dataset.action !== 'model-menu') {
    S.popover = null;
    renderPopover();
  }
  if (!el) return;
  const fn = actions[el.dataset.action];
  if (fn) {
    e.preventDefault();
    fn(el);
  }
});

document.addEventListener('input', (e) => {
  const t = e.target;
  if (t.id === 'prompt') {
    const had = !!S.draft.trim();
    S.draft = t.value;
    autosize();
    const btn = $('.send:not(.stop)');
    if (btn && had !== !!S.draft.trim()) btn.disabled = !S.draft.trim();
    return;
  }
  if (t.dataset.bind) {
    S.form[t.dataset.bind] = t.value;
    if (t.dataset.bind === 'srvType') render();
  }
});

document.addEventListener('change', async (e) => {
  const t = e.target;
  const kind = t.dataset.change;
  if (!kind) return;
  if (kind === 'provider-url') {
    const providers = S.settings.providers.map((p) => (p.id === t.dataset.id ? { ...p, baseUrl: t.value.trim() } : p));
    await saveSettings({ providers });
    detect();
  } else if (kind === 'context') {
    await saveSettings({ contextLength: Number(t.value) });
  } else if (kind === 'temperature') {
    await saveSettings({ temperature: Number(t.value) });
  } else if (kind === 'port') {
    const port = Number(t.value);
    if (!Number.isInteger(port) || port < 1024 || port > 65535) return toast('Use a port between 1024 and 65535');
    await saveSettings({ bridgePort: port });
    toast('Bridge restarted. Update the plugin so it uses the new port.');
  }
});

document.addEventListener('keydown', (e) => {
  const pending = S.current && Object.values(S.permissions).find((p) => p.sessionId === S.current.id);
  if (e.target.id === 'prompt') {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (pending && !S.draft.trim()) return respondPermission(pending.requestId, 'once');
      send();
      return;
    }
    if (e.key === 'Tab' && e.shiftKey) {
      e.preventDefault();
      cycleMode();
      return;
    }
  }
  if (e.key === 'Escape') {
    if (S.popover) {
      S.popover = null;
      renderPopover();
    } else if (pending) {
      respondPermission(pending.requestId, 'deny');
    } else if (S.current && S.running.has(S.current.id)) {
      api.invoke('chat:stop', S.current.id);
    }
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
    e.preventDefault();
    newSession();
  }
});

window.addEventListener('resize', () => S.popover && renderPopover());

/* ---------------------------------------------------------------- events */

api.on('chat:event', async (ev) => {
  const sid = ev.sessionId;
  const isCurrent = S.current?.id === sid;
  switch (ev.type) {
    case 'stream':
      S.stream[sid] = { content: ev.content, reasoning: ev.reasoning };
      if (isCurrent && S.view === 'chat') renderStreamOnly();
      return;
    case 'sync':
      S.stream[sid] = null;
      if (isCurrent) S.current = ev.session;
      for (const m of ev.session.messages) if (m.role === 'tool') S.toolRunning.delete(m.tool_call_id);
      break;
    case 'running':
      if (ev.running) S.running.add(sid);
      else {
        S.running.delete(sid);
        for (const [id, p] of Object.entries(S.permissions)) if (p.sessionId === sid) delete S.permissions[id];
      }
      await refreshSessions();
      break;
    case 'permission':
      S.permissions[ev.requestId] = ev;
      if (!isCurrent) toast('A session is waiting for your permission');
      break;
    case 'permission_done':
      delete S.permissions[ev.requestId];
      break;
    case 'tool_running':
      S.toolRunning.add(ev.toolCallId);
      break;
    case 'error':
      toast(ev.message);
      S.running.delete(sid);
      break;
  }
  if (S.view === 'chat' && (isCurrent || ev.type === 'running')) render();
  else if (ev.type === 'running') render();
});

api.on('studio:status', (s) => {
  S.studio = { ...S.studio, ...s };
  render();
});

api.on('mcp:status', async (s) => {
  S.mcp = s;
  await refreshTools();
  render();
});

/* ------------------------------------------------------------------ boot */

(async function boot() {
  document.body.classList.add(`platform-${api.platform}`);
  S.info = await api.invoke('app:info');
  S.settings = await api.invoke('settings:get');
  S.studio = { ...S.studio, ...(await api.invoke('studio:status')) };
  S.mcp = await api.invoke('mcp:status');
  await Promise.all([refreshSessions(), refreshTools()]);
  if (!S.settings.onboarded) S.view = 'onboarding';
  else if (S.sessions.length) S.current = await api.invoke('sessions:get', S.sessions[0].id);
  render();
  detect();
  setInterval(async () => {
    // Pick up plugin installs done outside the app.
    const st = await api.invoke('studio:status');
    if (JSON.stringify(st.plugin) !== JSON.stringify(S.studio.plugin)) {
      S.studio = { ...S.studio, ...st };
      render();
    }
  }, 5000);
})();
