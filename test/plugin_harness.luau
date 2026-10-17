-- Runs plugin/BloxBridge.lua against a tiny mock of the Roblox API.
-- test/plugin.test.js prepends `local PLUGIN_SOURCE = <plugin source>` and runs it with the luau CLI.

---------------------------------------------------------------- datatypes
local Vector3 = {}
Vector3.__index = Vector3
function Vector3.new(x, y, z)
	return setmetatable({ X = x or 0, Y = y or 0, Z = z or 0, __type = "Vector3" }, Vector3)
end

local Color3 = {}
Color3.__index = Color3
function Color3.new(r, g, b)
	return setmetatable({ R = r, G = g, B = b, __type = "Color3" }, Color3)
end
function Color3.fromRGB(r, g, b)
	return Color3.new(r / 255, g / 255, b / 255)
end
function Color3.fromHex(h)
	h = h:gsub("#", "")
	return Color3.fromRGB(tonumber(h:sub(1, 2), 16), tonumber(h:sub(3, 4), 16), tonumber(h:sub(5, 6), 16))
end
function Color3:ToHex()
	return string.format("%02X%02X%02X", math.floor(self.R * 255 + 0.5), math.floor(self.G * 255 + 0.5), math.floor(self.B * 255 + 0.5))
end

local MaterialEnum = { __type = "Enum" }
local function enumItem(name)
	return { Name = name, EnumType = MaterialEnum, __type = "EnumItem", __tostring = "Enum.Material." .. name }
end
MaterialEnum.Plastic = enumItem("Plastic")
MaterialEnum.Neon = enumItem("Neon")

local realTypeof = typeof
local function mockTypeof(v)
	if type(v) == "table" and rawget(v, "__type") then
		return rawget(v, "__type")
	end
	if type(v) == "table" and rawget(v, "__instance") then
		return "Instance"
	end
	return realTypeof(v)
end

---------------------------------------------------------------- instances
local CLASS_PROPS = {
	Part = { Position = Vector3.new(0, 0, 0), Size = Vector3.new(4, 1, 2), Color = Color3.new(0.6, 0.6, 0.6), Material = MaterialEnum.Plastic, Anchored = false, Transparency = 0 },
	Script = { Source = "", Disabled = false },
	ModuleScript = { Source = "" },
	LocalScript = { Source = "" },
	Folder = {},
	Model = { PrimaryPart = nil },
}
local IS = {
	Script = { LuaSourceContainer = true, BaseScript = true },
	LocalScript = { LuaSourceContainer = true, BaseScript = true },
	ModuleScript = { LuaSourceContainer = true },
	Part = { BasePart = true },
}

local Instance = {}
local Methods = {}

function Methods.GetChildren(self)
	local out = {}
	for _, c in ipairs(rawget(self, "__children")) do
		table.insert(out, c)
	end
	return out
end
function Methods.FindFirstChild(self, name)
	for _, c in ipairs(rawget(self, "__children")) do
		if c.Name == name then
			return c
		end
	end
	return nil
end
function Methods.GetDescendants(self)
	local out = {}
	local function walk(i)
		for _, c in ipairs(rawget(i, "__children")) do
			table.insert(out, c)
			walk(c)
		end
	end
	walk(self)
	return out
end
function Methods.IsA(self, cls)
	return self.ClassName == cls or cls == "Instance" or (IS[self.ClassName] and IS[self.ClassName][cls]) or false
end
function Methods.GetAttributes(self)
	return rawget(self, "__attrs")
end
function Methods.SetAttribute(self, k, v)
	rawget(self, "__attrs")[k] = v
end
function Methods.GetAttribute(self, k)
	return rawget(self, "__attrs")[k]
end
function Methods.GetService(self, name)
	local s = Methods.FindFirstChild(self, name)
	if not s then
		error("'" .. name .. "' is not a valid Service name")
	end
	return s
end

local InstanceMeta = {}
InstanceMeta.__index = function(self, key)
	if Methods[key] then
		return Methods[key]
	end
	local props = rawget(self, "__props")
	if props[key] ~= nil or rawget(self, "__known")[key] then
		return props[key]
	end
	local child = Methods.FindFirstChild(self, key)
	if child then
		return child
	end
	error(key .. " is not a valid member of " .. props.ClassName, 2)
end
InstanceMeta.__newindex = function(self, key, value)
	local props = rawget(self, "__props")
	if key == "Parent" then
		local old = props.Parent
		if old then
			local list = rawget(old, "__children")
			for i, c in ipairs(list) do
				if c == self then
					table.remove(list, i)
					break
				end
			end
		end
		props.Parent = value
		if value then
			table.insert(rawget(value, "__children"), self)
		end
		return
	end
	if key ~= "Name" and not rawget(self, "__known")[key] then
		error(key .. " is not a valid member of " .. props.ClassName, 2)
	end
	props[key] = value
end

function Instance.new(className, parent)
	local known = { Name = true, Parent = true, ClassName = true }
	local props = { Name = className, ClassName = className }
	for k, v in pairs(CLASS_PROPS[className] or {}) do
		known[k] = true
		props[k] = v
	end
	if className == "Model" then
		known.PrimaryPart = true
	end
	local inst = setmetatable({ __instance = true, __props = props, __children = {}, __attrs = {}, __known = known }, InstanceMeta)
	if parent then
		inst.Parent = parent
	end
	return inst
end

---------------------------------------------------------------- services
local game = Instance.new("DataModel")
game.Name = "Test Place"
local function svc(name)
	local s = Instance.new(name)
	s.Parent = game
	return s
end
local Workspace = svc("Workspace")
local SSS = svc("ServerScriptService")
svc("ReplicatedStorage")
svc("Lighting")

local selection = {}
local function service(name, impl)
	local s = svc(name)
	for k, v in pairs(impl) do
		Methods[k] = Methods[k] or nil
		rawget(s, "__props")[k] = v
		rawget(s, "__known")[k] = true
	end
	return s
end

local requests = {}
local commands = {}
local results = {}

service("HttpService", {
	JSONEncode = function(_, v)
		return v
	end,
	JSONDecode = function(_, v)
		return v
	end,
	UrlEncode = function(_, v)
		return v
	end,
	RequestAsync = function(_, req)
		table.insert(requests, req)
		if req.Method == "POST" then
			table.insert(results, req.Body)
			return { Success = true, StatusCode = 200, Body = "{}" }
		end
		local cmd = table.remove(commands, 1)
		if cmd then
			return { Success = true, StatusCode = 200, Body = cmd }
		end
		error("STOP")
	end,
})
service("RunService", { IsRunning = function() return false end })
service("Selection", {
	Get = function() return selection end,
	Set = function(_, list) selection = list end,
})
service("ChangeHistoryService", {
	TryBeginRecording = function() return "rec" end,
	FinishRecording = function() end,
})
service("ScriptEditorService", {
	UpdateSourceAsync = function(_, script, fn) script.Source = fn() end,
	FindScriptDocument = function() return nil end,
})
service("LogService", { GetLogHistory = function() return { { message = "hello", messageType = "Enum.MessageType.MessageOutput" } } end })

local Checkpoints = Instance.new("Folder", Workspace)
Checkpoints.Name = "Checkpoints"
for i = 1, 3 do
	local p = Instance.new("Part", Checkpoints)
	p.Name = "Pad" .. i
end

---------------------------------------------------------------- plugin stub
local pluginObj = {
	CreateToolbar = function()
		return {
			CreateButton = function()
				return { Click = { Connect = function() end }, SetActive = function() end }
			end,
		}
	end,
	GetSetting = function() return nil end,
	SetSetting = function() end,
	Unloading = { Connect = function() end },
}

local Enum = { FinishRecordingOperation = { Commit = "Commit", Cancel = "Cancel" }, Material = MaterialEnum }

local env = setmetatable({
	game = game,
	workspace = Workspace,
	plugin = pluginObj,
	Instance = Instance,
	Vector3 = Vector3,
	Color3 = Color3,
	Enum = Enum,
	typeof = mockTypeof,
	task = {
		spawn = function(fn, ...)
			local ok, err = pcall(fn, ...)
			if not ok and not tostring(err):find("STOP") then
				error(err)
			end
		end,
		wait = function() error("STOP") end,
	},
	print = function() end,
	warn = function() end,
	tostring = function(v)
		if type(v) == "table" and rawget(v, "__tostring") then
			return rawget(v, "__tostring")
		end
		return tostring(v)
	end,
}, { __index = _G })

-- Commands the "app" sends, in order.
commands = {
	{ id = "1", tool = "get_explorer_tree", args = {} },
	{ id = "2", tool = "find_instances", args = { query = "pad", class_name = "BasePart" } },
	{ id = "3", tool = "set_properties", args = { path = "Workspace.Checkpoints.Pad2", properties = { Position = { 1, 2, 3 }, Color = "#FF8800", Material = "Neon", Anchored = true, ["@Stage"] = 2 } } },
	{ id = "4", tool = "get_properties", args = { path = "workspace.Checkpoints.Pad2" } },
	{ id = "5", tool = "write_script", args = { path = "ServerScriptService.CheckpointHandler", source = "print('hi')\nreturn 1" } },
	{ id = "6", tool = "read_script", args = { path = "game.ServerScriptService.CheckpointHandler" } },
	{ id = "7", tool = "create_instance", args = { class_name = "Part", parent = "Workspace", name = "Lava", properties = { Size = { 10, 1, 10 } } } },
	{ id = "8", tool = "delete_instance", args = { path = "Workspace.Lava" } },
	{ id = "9", tool = "delete_instance", args = { path = "Workspace" } },
	{ id = "10", tool = "get_properties", args = { path = "Workspace.Nope" } },
	{ id = "11", tool = "nonexistent_tool", args = {} },
	{ id = "12", tool = "get_output_log", args = {} },
	{ id = "13", tool = "get_selection", args = {} },
	{ id = "14", tool = "run_code", args = { code = "print('pads', #workspace.Checkpoints:GetChildren())\nreturn workspace.Checkpoints.Pad1" } },
	{ id = "15", tool = "run_code", args = { code = "error('boom')" } },
	{ id = "16", tool = "run_code", args = { code = "this is not luau" } },
}

local f = assert(loadstring(PLUGIN_SOURCE, "BloxBridge"))
setfenv(f, env)
f()

local byId = {}
for _, r in ipairs(results) do
	byId[r.id] = r
end
local function ok(id)
	local r = byId[id]
	assert(r, "no result for " .. id)
	assert(r.ok, "command " .. id .. " failed: " .. tostring(r.error))
	return r.result
end

local tree = ok("1")
assert(tree.place == "Test Place")
assert(#ok("2").results == 3, "find_instances")
local setRes = ok("3")
assert(#setRes.errors == 0, "set_properties errors: " .. table.concat(setRes.errors, "; "))
local pad2 = Checkpoints:FindFirstChild("Pad2")
assert(pad2.Position.X == 1 and pad2.Position.Z == 3, "position")
assert(pad2.Color:ToHex() == "FF8800", "color")
assert(pad2.Material == MaterialEnum.Neon, "enum")
assert(pad2:GetAttribute("Stage") == 2, "attribute")
local props = ok("4")
assert(props.properties.Color == "#FF8800", "serialize color " .. tostring(props.properties.Color))
assert(props.properties.Position[2] == 2, "serialize vector")
assert(props.attributes.Stage == 2)
local w = ok("5")
assert(w.created == true and w.lines == 2, "write_script")
assert(SSS:FindFirstChild("CheckpointHandler").Source == "print('hi')\nreturn 1")
assert(ok("6").source == "print('hi')\nreturn 1")
local c = ok("7")
assert(c.path == "Workspace.Lava", "create path " .. tostring(c.path))
assert(Workspace:FindFirstChild("Lava") == nil, "delete")
assert(ok("8").deleted == "Workspace.Lava")
assert(byId["9"].ok == false and byId["9"].error:find("service"), "refuse service delete")
assert(byId["10"].ok == false and byId["10"].error:find("Not found"), "missing path error")
assert(byId["11"].ok == false, "unknown tool")
assert(ok("12").lines[1]:find("hello"))
assert(#ok("13").selection == 1, "selection after create")
local rc = ok("14")
assert(rc.output[1] == "pads 3", "run_code output " .. tostring(rc.output[1]))
assert(rc.returned[1] == "Workspace.Checkpoints.Pad1", "run_code return")
assert(byId["15"].ok == false and byId["15"].error:find("boom"), "runtime error")
assert(byId["16"].ok == false and byId["16"].error:find("Compile error"), "compile error")
for _, r in ipairs(requests) do
	assert(r.Headers["X-Blox-Bridge"] == "1")
	assert(r.Url:find("^http://127.0.0.1:44755/"))
end
print("PLUGIN_HARNESS_OK " .. #results .. " commands")
