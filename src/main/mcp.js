// MCP on both sides:
//  - McpHub is an MCP *client*: it connects to extra MCP servers the user adds
//    (stdio commands or HTTP URLs) and offers their tools to the model.
//  - createMcpHandler serves the Studio tools as an MCP *server* at /mcp on the
//    bridge, so other MCP clients (Claude Desktop, Cursor, ...) can use Studio too.

import { EventEmitter } from 'node:events';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport, getDefaultEnvironment } from '@modelcontextprotocol/sdk/client/stdio.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const CLIENT_INFO = { name: 'blox-bridge', version: '0.1.0' };

export class McpHub extends EventEmitter {
  constructor() {
    super();
    this.conns = new Map(); // id -> { config, client, tools, state, error }
  }

  async sync(configs) {
    const wanted = new Map(configs.filter((c) => c.enabled !== false).map((c) => [c.id, c]));
    for (const [id, conn] of this.conns) {
      if (!wanted.has(id) || JSON.stringify(wanted.get(id)) !== JSON.stringify(conn.config)) {
        await conn.client?.close().catch(() => {});
        this.conns.delete(id);
      }
    }
    await Promise.all([...wanted.values()].filter((c) => !this.conns.has(c.id)).map((c) => this.connect(c)));
    this.emit('status', this.status());
  }

  async connect(config) {
    const conn = { config, client: null, tools: [], state: 'connecting', error: null };
    this.conns.set(config.id, conn);
    this.emit('status', this.status());
    try {
      const client = new Client(CLIENT_INFO, { capabilities: {} });
      let transport;
      if (config.type === 'http') {
        transport = new StreamableHTTPClientTransport(new URL(config.url));
      } else {
        transport = new StdioClientTransport({
          command: config.command,
          args: splitArgs(config.args || ''),
          env: { ...getDefaultEnvironment(), PATH: process.env.PATH, ...(config.env || {}) },
          stderr: 'pipe',
        });
      }
      client.onclose = () => {
        if (this.conns.get(config.id) === conn) {
          conn.state = 'error';
          conn.error ||= 'Server closed the connection';
          this.emit('status', this.status());
        }
      };
      await client.connect(transport);
      const { tools } = await client.listTools();
      conn.client = client;
      conn.tools = tools || [];
      conn.state = 'connected';
    } catch (e) {
      conn.state = 'error';
      conn.error = String(e?.message || e);
    }
    this.emit('status', this.status());
  }

  status() {
    return [...this.conns.values()].map((c) => ({
      id: c.config.id,
      name: c.config.name,
      state: c.state,
      error: c.error,
      tools: c.tools.map((t) => t.name),
    }));
  }

  // Tools exposed to the model, namespaced as <server>__<tool>.
  tools() {
    const out = [];
    for (const c of this.conns.values()) {
      if (c.state !== 'connected') continue;
      const prefix = slug(c.config.name || c.config.id);
      for (const t of c.tools) {
        out.push({
          name: `${prefix}__${t.name}`.slice(0, 64),
          description: t.description || '',
          parameters: t.inputSchema || { type: 'object', properties: {} },
          category: t.annotations?.readOnlyHint ? 'read' : 'write',
          server: c.config.name,
          serverId: c.config.id,
          remoteName: t.name,
        });
      }
    }
    return out;
  }

  async call(tool, args) {
    const c = this.conns.get(tool.serverId);
    if (!c?.client) throw new Error(`MCP server ${tool.server} is not connected`);
    const res = await c.client.callTool({ name: tool.remoteName, arguments: args });
    const text = (res.content || [])
      .map((p) => (p.type === 'text' ? p.text : `[${p.type}]`))
      .join('\n');
    if (res.isError) throw new Error(text || 'Tool failed');
    return text || JSON.stringify(res.structuredContent ?? null);
  }

  async closeAll() {
    for (const c of this.conns.values()) await c.client?.close().catch(() => {});
  }
}

export function createMcpHandler({ getTools, callTool }) {
  return async (req, res, body) => {
    const server = new Server(CLIENT_INFO, { capabilities: { tools: {} } });
    server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: getTools().map((t) => ({ name: t.name, description: t.description, inputSchema: t.parameters })),
    }));
    server.setRequestHandler(CallToolRequestSchema, async (r) => {
      try {
        const out = await callTool(r.params.name, r.params.arguments || {});
        return { content: [{ type: 'text', text: typeof out === 'string' ? out : JSON.stringify(out, null, 2) }] };
      } catch (e) {
        return { content: [{ type: 'text', text: String(e?.message || e) }], isError: true };
      }
    });
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, body);
  };
}

function slug(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'mcp';
}

// Splits a command-line argument string, honouring double and single quotes.
export function splitArgs(s) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m;
  while ((m = re.exec(s))) out.push(m[1] ?? m[2] ?? m[3]);
  return out;
}
