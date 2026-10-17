// Roblox Studio tools. The plugin (plugin/BloxBridge.lua) implements each one;
// the app forwards calls to it over the local bridge.
//
// category decides the default permission:
//   read  -> allowed without asking
//   write -> asks first (auto-accepted in "Auto-accept edits" mode)
//   run   -> always asks unless set to Allow in Settings

const path = {
  type: 'string',
  description: 'Instance path, dot separated, e.g. "Workspace.Checkpoints.Pad1" or "ServerScriptService.Main".',
};

export const STUDIO_TOOLS = [
  {
    name: 'get_explorer_tree',
    category: 'read',
    description:
      'List the Explorer hierarchy under an instance. Omit path to get the top-level services. Returns names, classes and child counts.',
    parameters: {
      type: 'object',
      properties: {
        path: { ...path, description: path.description + ' Omit for the top-level services.' },
        depth: { type: 'integer', description: 'How many levels to expand (1-5). Default 2.' },
        max_children: { type: 'integer', description: 'Max children listed per instance. Default 40.' },
      },
    },
  },
  {
    name: 'find_instances',
    category: 'read',
    description:
      'Search descendants by name (case-insensitive substring) and/or ClassName. Use this to locate things before editing them.',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'Part of the instance name to match.' },
        class_name: { type: 'string', description: 'Only match this class, e.g. "Part", "Script", "RemoteEvent". IsA() is used, so "BasePart" matches all parts.' },
        root: { ...path, description: 'Where to search. Default "game".' },
        limit: { type: 'integer', description: 'Max results. Default 50.' },
      },
    },
  },
  {
    name: 'get_properties',
    category: 'read',
    description:
      'Read properties and attributes of an instance. Without "properties", returns the common ones for its class.',
    parameters: {
      type: 'object',
      properties: {
        path,
        properties: { type: 'array', items: { type: 'string' }, description: 'Specific property names to read.' },
      },
      required: ['path'],
    },
  },
  {
    name: 'get_selection',
    category: 'read',
    description: 'Get the paths of the instances the user has selected in Studio.',
    parameters: { type: 'object', properties: {} },
  },
  {
    name: 'read_script',
    category: 'read',
    description: 'Read the source of a Script, LocalScript or ModuleScript.',
    parameters: { type: 'object', properties: { path }, required: ['path'] },
  },
  {
    name: 'get_output_log',
    category: 'read',
    description: 'Read recent lines from the Studio Output window (prints, warnings, errors).',
    parameters: {
      type: 'object',
      properties: { limit: { type: 'integer', description: 'How many recent lines. Default 50.' } },
    },
  },
  {
    name: 'set_selection',
    category: 'read',
    description: 'Select instances in Studio so the user can see them in the Explorer.',
    parameters: {
      type: 'object',
      properties: { paths: { type: 'array', items: { type: 'string' } } },
      required: ['paths'],
    },
  },
  {
    name: 'create_instance',
    category: 'write',
    description:
      'Create a new instance. Property values: numbers/booleans/strings as-is, Vector3 as [x,y,z], Color3 as "#RRGGBB" or [r,g,b] (0-255), UDim2 as [xScale,xOffset,yScale,yOffset], enums as "Neon" or "Enum.Material.Neon", instance refs as paths. Keys starting with "@" set attributes.',
    parameters: {
      type: 'object',
      properties: {
        class_name: { type: 'string', description: 'e.g. "Part", "Model", "Script", "ScreenGui".' },
        parent: { ...path, description: 'Path of the parent instance.' },
        name: { type: 'string' },
        properties: { type: 'object', description: 'Property name -> value.' },
        source: { type: 'string', description: 'Luau source, if creating a script.' },
      },
      required: ['class_name', 'parent'],
    },
  },
  {
    name: 'set_properties',
    category: 'write',
    description:
      'Change properties on an instance. Same value formats as create_instance. Keys starting with "@" set attributes, e.g. {"@Stage": 3}.',
    parameters: {
      type: 'object',
      properties: { path, properties: { type: 'object', description: 'Property name -> value.' } },
      required: ['path', 'properties'],
    },
  },
  {
    name: 'write_script',
    category: 'write',
    description:
      'Replace the whole source of a script. If the script does not exist it is created at that path (class_name defaults to Script).',
    parameters: {
      type: 'object',
      properties: {
        path,
        source: { type: 'string', description: 'The complete new Luau source.' },
        class_name: { type: 'string', enum: ['Script', 'LocalScript', 'ModuleScript'] },
      },
      required: ['path', 'source'],
    },
  },
  {
    name: 'delete_instance',
    category: 'write',
    description: 'Delete an instance (undoable with Ctrl+Z in Studio).',
    parameters: { type: 'object', properties: { path }, required: ['path'] },
  },
  {
    name: 'run_code',
    category: 'run',
    description:
      'Run Luau in Studio edit mode with plugin permissions, for bulk edits or inspection. print() output and return values come back. Changes are one undo step.',
    parameters: {
      type: 'object',
      properties: { code: { type: 'string', description: 'Luau code to run.' } },
      required: ['code'],
    },
  },
];

export const STUDIO_TOOL_NAMES = new Set(STUDIO_TOOLS.map((t) => t.name));

export function defaultPermission(category) {
  return category === 'read' ? 'allow' : 'ask';
}

export const SYSTEM_PROMPT = `You are Blox Bridge, a coding assistant working inside Roblox Studio for the user.
You can see and change the open place through tools. Rules:
- Look before you edit: use get_explorer_tree, find_instances, get_properties or read_script to learn what exists.
- Instance paths are dot separated from the DataModel, e.g. Workspace.Map.SpawnLocation or ServerScriptService.GameLoop.
- Write idiomatic Luau. Server logic goes in Scripts under ServerScriptService, client logic in LocalScripts under StarterPlayer.StarterPlayerScripts or StarterGui, shared code in ModuleScripts under ReplicatedStorage.
- Use write_script with the complete source; never leave placeholders like "-- rest of code".
- Prefer create_instance / set_properties for a few objects and run_code for bulk changes.
- If a tool returns an error, read it, fix the cause and retry once; otherwise explain the problem.
- Keep replies short. When done, say what changed and how the user can test it (e.g. press Play).`;
