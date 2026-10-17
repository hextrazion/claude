import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { StudioBridge } from '../src/main/bridge.js';
import { createMcpHandler, splitArgs } from '../src/main/mcp.js';
import { splitThink, parseArgs } from '../src/main/llm.js';
import { Agent } from '../src/main/agent.js';
import { STUDIO_TOOLS } from '../src/main/tools.js';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

const PORT = 47311;
const base = `http://127.0.0.1:${PORT}`;
const H = { 'X-Blox-Bridge': '1', 'X-Blox-Place': encodeURIComponent('My Obby.rbxl') };

// Acts like the Studio plugin: long-polls and answers commands.
function fakePlugin(handlers) {
  let on = true;
  (async () => {
    while (on) {
      const r = await fetch(`${base}/poll`, { headers: H }).catch(() => null);
      if (!r) { await new Promise((s) => setTimeout(s, 50)); continue; }
      if (r.status !== 200) continue;
      const cmd = await r.json();
      let body;
      try {
        body = { id: cmd.id, ok: true, result: await handlers[cmd.tool](cmd.args) };
      } catch (e) {
        body = { id: cmd.id, ok: false, error: e.message };
      }
      await fetch(`${base}/result`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    }
  })();
  return () => { on = false; };
}

test('splitThink and parseArgs', () => {
  assert.deepEqual(splitThink('<think>plan</think>\nHello'), { content: 'Hello', thinking: 'plan' });
  assert.deepEqual(splitThink('<think>still going'), { content: '', thinking: 'still going' });
  assert.deepEqual(parseArgs('```json\n{"path":"Workspace"}\n```'), { path: 'Workspace' });
  assert.deepEqual(parseArgs({ a: 1 }), { a: 1 });
  assert.deepEqual(splitArgs('-y "@scope/pkg" \'C:/My Dir\''), ['-y', '@scope/pkg', 'C:/My Dir']);
});

test('bridge, MCP endpoint and agent loop', async (t) => {
  const bridge = new StudioBridge(PORT);
  bridge.mcpHandler = createMcpHandler({ getTools: () => STUDIO_TOOLS, callTool: (n, a) => bridge.call(n, a) });
  bridge.start();
  await new Promise((r) => setTimeout(r, 100));
  t.after(() => bridge.stop());

  // Security: browser-style and header-less requests are refused.
  assert.equal((await fetch(`${base}/poll`)).status, 403);
  assert.equal((await fetch(`${base}/poll`, { headers: { ...H, Origin: 'https://evil.example' } })).status, 403);

  await assert.rejects(bridge.call('get_selection', {}), /not connected/);

  const stop = fakePlugin({
    get_selection: () => ({ selection: [{ path: 'Workspace.Pad1', class: 'Part' }] }),
    get_explorer_tree: () => ({ place: 'My Obby', services: [{ name: 'Workspace', class: 'Workspace', children_count: 3 }] }),
    write_script: (a) => ({ path: a.path, created: true, lines: a.source.split('\n').length }),
    delete_instance: () => { throw new Error('Refusing to delete a service'); },
  });
  t.after(stop);
  await new Promise((r) => setTimeout(r, 150));

  assert.equal(bridge.status().connected, true);
  assert.equal(bridge.status().place, 'My Obby.rbxl');
  assert.deepEqual(await bridge.call('get_selection', {}), { selection: [{ path: 'Workspace.Pad1', class: 'Part' }] });
  await assert.rejects(bridge.call('delete_instance', { path: 'Workspace' }), /Refusing/);

  // MCP clients can list and call Studio tools through /mcp.
  const client = new Client({ name: 'test', version: '1' });
  await client.connect(new StreamableHTTPClientTransport(new URL(`${base}/mcp`)));
  const { tools } = await client.listTools();
  assert.ok(tools.some((x) => x.name === 'run_code'));
  const res = await client.callTool({ name: 'get_selection', arguments: {} });
  assert.match(res.content[0].text, /Workspace\.Pad1/);
  await client.close();

  // Fake Ollama: first turn calls two tools, second turn answers.
  let turn = 0;
  const seen = [];
  const ollama = http.createServer((req, res) => {
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      const j = JSON.parse(body);
      seen.push(j);
      res.writeHead(200, { 'Content-Type': 'application/x-ndjson' });
      if (turn++ === 0) {
        res.write(JSON.stringify({ message: { role: 'assistant', content: '<think>look first</think>Checking.' } }) + '\n');
        res.write(JSON.stringify({ message: { role: 'assistant', content: '', tool_calls: [
          { function: { name: 'get_explorer_tree', arguments: {} } },
          { function: { name: 'write_script', arguments: { path: 'ServerScriptService.Main', source: 'print(1)\nprint(2)' } } },
        ] } }) + '\n');
      } else {
        res.write(JSON.stringify({ message: { role: 'assistant', content: 'Done.' } }) + '\n');
      }
      res.end(JSON.stringify({ done: true }) + '\n');
    });
  });
  await new Promise((r) => ollama.listen(47312, '127.0.0.1', r));
  t.after(() => ollama.close());

  const session = { id: 's1', title: 'New session', messages: [] };
  let settings = {
    providers: [{ id: 'ollama', name: 'Ollama', kind: 'ollama', baseUrl: 'http://127.0.0.1:47312' }],
    model: { providerId: 'ollama', id: 'qwen2.5-coder:7b' },
    mode: 'ask',
    permissions: {},
    contextLength: 8192,
  };
  const store = {
    getSettings: () => settings,
    setSettings: (p) => (settings = { ...settings, ...p }),
    getSession: () => session,
    saveSession: () => {},
  };
  const events = [];
  const agent = new Agent({
    store,
    bridge,
    hub: { tools: () => [] },
    emit: (sid, ev) => {
      events.push(ev);
      // write_script asks for permission by default: approve it.
      if (ev.type === 'permission') {
        assert.equal(ev.tool, 'write_script');
        setTimeout(() => agent.respondPermission(ev.requestId, 'once'), 10);
      }
    },
  });
  await agent.send('s1', 'make a script');

  const roles = session.messages.map((m) => m.role);
  assert.deepEqual(roles, ['user', 'assistant', 'tool', 'tool', 'assistant']);
  assert.equal(session.messages[1].reasoning, 'look first');
  assert.equal(session.messages[1].content, 'Checking.');
  assert.equal(session.messages[2].status, 'ok');
  assert.match(session.messages[3].content, /"created": true/);
  assert.equal(session.messages[4].content, 'Done.');
  assert.equal(session.title, 'make a script');
  assert.equal(seen[0].options.num_ctx, 8192);
  // Tool results go back to Ollama with tool_name, assistant calls with object arguments.
  const second = seen[1].messages;
  assert.equal(second.at(-1).role, 'tool');
  assert.equal(second.at(-1).tool_name, 'write_script');
  assert.equal(typeof second.at(-3).tool_calls[0].function.arguments, 'object');
  assert.ok(events.some((e) => e.type === 'permission'));

  // Read-only mode hides write tools from the model.
  settings.mode = 'readonly';
  assert.ok(!agent.activeTools().some((x) => x.name === 'write_script'));
  settings.permissions = { get_selection: 'off' };
  assert.ok(!agent.activeTools().some((x) => x.name === 'get_selection'));
});
