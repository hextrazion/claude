# Blox Bridge

A desktop app that connects **any model you've downloaded** (Ollama, LM Studio, llama.cpp, Jan, or any OpenAI-compatible server) to **Roblox Studio** over MCP. You chat with it like a coding assistant: it reads your place, writes scripts, creates parts, and asks before it changes anything.

Everything runs on your computer. The app and Studio talk over `127.0.0.1` only.

## Download

Get the installer for your OS from the **Releases** page, or from the latest **Actions → Build app** run (Artifacts):

| OS | File |
|---|---|
| Windows | `Blox-Bridge-Setup-x.y.z.exe` (installer) or `Blox-Bridge-Portable-x.y.z.exe` |
| macOS | `Blox-Bridge-x.y.z-arm64.dmg` (Apple Silicon) / `-x64.dmg` (Intel) |
| Linux | `Blox-Bridge-x.y.z.AppImage` (Studio itself doesn't run on Linux, but you can use the MCP endpoint remotely) |

The builds are not code-signed yet, so your OS warns the first time:

- **Windows:** click **More info → Run anyway**.
- **macOS** ("Blox Bridge" Not Opened): click **Done**, open **System Settings → Privacy & Security**, scroll down and click **Open Anyway** next to Blox Bridge, then confirm. Or run this once in Terminal after dragging the app to Applications:

  ```bash
  xattr -dr com.apple.quarantine "/Applications/Blox Bridge.app"
  ```

## Setup (2 minutes)

1. **Get a model.** Install [Ollama](https://ollama.com/download) and run `ollama pull qwen2.5-coder:7b` (or `:14b` if you have 16 GB+ of RAM/VRAM). Any model with tool calling works: qwen2.5-coder, qwen3, llama3.1, mistral-nemo, gpt-oss… LM Studio, llama.cpp `llama-server` and Jan are detected automatically when their local server is on.
2. **Open Blox Bridge.** It finds your models. Pick one marked **Tools**.
3. **Click Install plugin.** It copies `BloxBridge.lua` into your Studio Plugins folder.
4. **Open Roblox Studio** (restart it if it was open). When Studio asks if Blox Bridge may connect to `127.0.0.1`, click **Allow**. The app shows **Studio connected**.

Then just ask: *"Add a checkpoint system to my obby"*, *"Explain how my place is organized"*, *"Find bugs in my scripts"*.

## What the model can do

| Tool | Default |
|---|---|
| `get_explorer_tree`, `find_instances`, `get_properties`, `get_selection`, `set_selection`, `read_script`, `get_output_log` | Allow |
| `create_instance`, `set_properties`, `write_script`, `delete_instance` | Ask |
| `run_code` (runs Luau in edit mode) | Ask |

Change any of these in **Settings → Tools & permissions** (Allow / Ask / Off). The mode chip in the message box switches between **Ask before edits**, **Auto-accept edits** and **Read only** (Shift+Tab). Every change the model makes is a single undo step in Studio (Ctrl+Z).

## MCP, both ways

- **Add more tools:** Settings → MCP servers accepts any stdio command (`npx -y @modelcontextprotocol/server-filesystem C:/Projects`) or Streamable HTTP URL. Their tools are offered to your model next to the Studio tools.
- **Use Studio from other MCP apps:** while Blox Bridge is open, Studio is served at `http://127.0.0.1:44755/mcp`. For stdio-only clients like Claude Desktop:

  ```json
  { "mcpServers": { "roblox-studio": { "command": "npx", "args": ["-y", "mcp-remote", "http://127.0.0.1:44755/mcp"] } } }
  ```

## How it works

```
 Ollama / LM Studio / llama.cpp ──chat + tool calls──▶ Blox Bridge app ◀── other MCP clients (/mcp)
                                                           │  local HTTP bridge (127.0.0.1:44755)
                                                           ▼
                                               Studio plugin (long-polls for commands)
```

- `src/main/llm.js`: model clients (Ollama native API with configurable context length; OpenAI-compatible streaming for the rest), `<think>` handling.
- `src/main/agent.js`: the agent loop and permission prompts.
- `src/main/bridge.js`: the local bridge. Refuses browser requests (Origin header), foreign Host headers (DNS rebinding), and plugin calls without the `X-Blox-Bridge` header.
- `src/main/mcp.js`: MCP client hub for extra servers, plus the MCP server endpoint.
- `plugin/BloxBridge.lua`: the Studio plugin.
- `src/renderer/`: the UI.

## Develop

```bash
npm install
npm start          # run the app
npm run check      # syntax check + tests (set LUAU=/path/to/luau to also test the plugin)
npm run dist       # build installers for the current OS into dist/
```

Push a tag like `v0.1.0` to build Windows, macOS and Linux installers on GitHub Actions and attach them to a release.
