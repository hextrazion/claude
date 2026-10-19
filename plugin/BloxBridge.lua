--[[
	Blox Bridge — Roblox Studio plugin
	Connects Studio to the Blox Bridge desktop app so a local model can read
	and edit your place. Everything stays on 127.0.0.1.

	The app installs this file into your Studio Plugins folder for you.
	The first time it connects, Studio asks whether Blox Bridge may access
	127.0.0.1. Click Allow.
]]

local HttpService = game:GetService("HttpService")
local RunService = game:GetService("RunService")
local Selection = game:GetService("Selection")
local ChangeHistoryService = game:GetService("ChangeHistoryService")
local ScriptEditorService = game:GetService("ScriptEditorService")
local LogService = game:GetService("LogService")

-- Plugins also load inside Play sessions; only run in the edit DataModel.
if RunService:IsRunning() then
	return
end

local PORT = 44755
local VERSION = "0.2.0"
local BASE = "http://127.0.0.1:" .. PORT
local SETTING = "BloxBridgeAutoConnect"

local toolbar = plugin:CreateToolbar("Blox Bridge")
local button = toolbar:CreateButton(
	"BloxBridgeConnect",
	"Connect this place to the Blox Bridge app",
	"",
	"Connect"
)
button.ClickableWhenViewportHidden = true

local enabled = plugin:GetSetting(SETTING)
if enabled == nil then
	enabled = true
end
local generation = 0
local connected = false

------------------------------------------------------------------------
-- Paths and values
------------------------------------------------------------------------

local function pathOf(inst)
	if inst == game then
		return "game"
	end
	local parts = {}
	local cur = inst
	while cur and cur ~= game do
		table.insert(parts, 1, cur.Name)
		cur = cur.Parent
	end
	return table.concat(parts, ".")
end

local function resolve(path)
	if type(path) ~= "string" or path == "" or path == "game" then
		return game
	end
	path = path:gsub("^game[%./]", "")
	local cur = game
	for seg in string.gmatch(path, "[^%./]+") do
		local nextInst = cur:FindFirstChild(seg)
		if not nextInst and cur == game then
			if seg:lower() == "workspace" then
				nextInst = workspace
			else
				local ok, svc = pcall(game.GetService, game, seg)
				if ok then
					nextInst = svc
				end
			end
		end
		if not nextInst then
			error(string.format("Not found: '%s' in %s", seg, pathOf(cur)), 0)
		end
		cur = nextInst
	end
	return cur
end

local function round(n)
	return math.floor(n * 1000 + 0.5) / 1000
end

local function serialize(v)
	local t = typeof(v)
	if t == "nil" or t == "boolean" or t == "string" then
		return v
	elseif t == "number" then
		return round(v)
	elseif t == "Vector3" then
		return { round(v.X), round(v.Y), round(v.Z) }
	elseif t == "Vector2" then
		return { round(v.X), round(v.Y) }
	elseif t == "Color3" then
		return "#" .. v:ToHex()
	elseif t == "BrickColor" then
		return v.Name
	elseif t == "UDim2" then
		return { round(v.X.Scale), v.X.Offset, round(v.Y.Scale), v.Y.Offset }
	elseif t == "UDim" then
		return { round(v.Scale), v.Offset }
	elseif t == "CFrame" then
		local rx, ry, rz = v:ToOrientation()
		return {
			position = { round(v.X), round(v.Y), round(v.Z) },
			orientation = { round(math.deg(rx)), round(math.deg(ry)), round(math.deg(rz)) },
		}
	elseif t == "EnumItem" then
		return tostring(v)
	elseif t == "Instance" then
		return pathOf(v)
	else
		return tostring(v)
	end
end

local function num(tbl, i, key)
	return tonumber(tbl[i] or tbl[key] or tbl[key:lower()]) or 0
end

local function toColor3(v)
	if type(v) == "string" then
		return Color3.fromHex(v)
	end
	local r, g, b = num(v, 1, "R"), num(v, 2, "G"), num(v, 3, "B")
	if r > 1 or g > 1 or b > 1 then
		return Color3.fromRGB(r, g, b)
	end
	return Color3.new(r, g, b)
end

-- Convert a JSON value into the type the property currently holds.
local function deserialize(current, v, propName)
	local t = typeof(current)
	if propName == "Parent" or t == "Instance" then
		if type(v) == "string" then
			return resolve(v)
		end
		return v
	end
	if t == "Vector3" and type(v) == "table" then
		return Vector3.new(num(v, 1, "X"), num(v, 2, "Y"), num(v, 3, "Z"))
	elseif t == "Vector2" and type(v) == "table" then
		return Vector2.new(num(v, 1, "X"), num(v, 2, "Y"))
	elseif t == "Color3" then
		return toColor3(v)
	elseif t == "BrickColor" then
		return BrickColor.new(v)
	elseif t == "UDim2" and type(v) == "table" then
		return UDim2.new(tonumber(v[1]) or 0, tonumber(v[2]) or 0, tonumber(v[3]) or 0, tonumber(v[4]) or 0)
	elseif t == "UDim" and type(v) == "table" then
		return UDim.new(tonumber(v[1]) or 0, tonumber(v[2]) or 0)
	elseif t == "CFrame" and type(v) == "table" then
		if v.position then
			local p = v.position
			local cf = CFrame.new(num(p, 1, "X"), num(p, 2, "Y"), num(p, 3, "Z"))
			local o = v.orientation
			if o then
				cf = cf
					* CFrame.fromOrientation(
						math.rad(num(o, 1, "X")),
						math.rad(num(o, 2, "Y")),
						math.rad(num(o, 3, "Z"))
					)
			end
			return cf
		elseif #v == 12 then
			return CFrame.new(table.unpack(v))
		end
		return CFrame.new(num(v, 1, "X"), num(v, 2, "Y"), num(v, 3, "Z"))
	elseif t == "EnumItem" and type(v) == "string" then
		local name = v:match("([^%.]+)$")
		return current.EnumType[name]
	elseif t == "nil" and type(v) == "string" then
		-- Unset references (PrimaryPart, Adornee, ObjectValue.Value...)
		local ok, inst = pcall(resolve, v)
		if ok and inst ~= game then
			return inst
		end
	end
	return v
end

local function setProps(inst, props)
	local errors = {}
	local parent = nil
	for key, value in pairs(props or {}) do
		local ok, err = pcall(function()
			if key:sub(1, 1) == "@" then
				inst:SetAttribute(key:sub(2), value)
			elseif key == "Parent" then
				parent = resolve(value)
			elseif key == "Source" and inst:IsA("LuaSourceContainer") then
				inst.Source = value
			else
				inst[key] = deserialize(inst[key], value, key)
			end
		end)
		if not ok then
			table.insert(errors, key .. ": " .. tostring(err))
		end
	end
	return errors, parent
end

local COMMON = {
	"Name", "ClassName", "Parent", "Position", "Size", "Orientation", "CFrame", "Color", "BrickColor",
	"Material", "Transparency", "Reflectance", "Anchored", "CanCollide", "CanTouch", "CastShadow", "Shape",
	"Text", "TextColor3", "TextSize", "TextScaled", "Font", "BackgroundColor3", "BackgroundTransparency",
	"AnchorPoint", "Visible", "Enabled", "Value", "Disabled", "RunContext", "Brightness", "Range",
	"Health", "MaxHealth", "WalkSpeed", "JumpPower", "PrimaryPart", "Image", "ZIndex", "LayoutOrder",
	"SoundId", "Volume", "Looped", "AnimationId", "MeshId", "TextureID", "ClockTime", "Ambient",
}

------------------------------------------------------------------------
-- Undo history
------------------------------------------------------------------------

local function withHistory(name, fn)
	local id = ChangeHistoryService:TryBeginRecording("Blox Bridge: " .. name)
	local ok, res = pcall(fn)
	if id then
		ChangeHistoryService:FinishRecording(
			id,
			if ok then Enum.FinishRecordingOperation.Commit else Enum.FinishRecordingOperation.Cancel
		)
	end
	if not ok then
		error(res, 0)
	end
	return res
end

local function setSource(script, source)
	local ok = pcall(function()
		ScriptEditorService:UpdateSourceAsync(script, function()
			return source
		end)
	end)
	if not ok then
		script.Source = source
	end
end

------------------------------------------------------------------------
-- Tools
------------------------------------------------------------------------

local tools = {}

local TOP_LEVEL = {
	"Workspace", "Players", "Lighting", "ReplicatedStorage", "ServerScriptService", "ServerStorage",
	"StarterGui", "StarterPack", "StarterPlayer", "Teams", "SoundService",
}

local function node(inst, depth, maxChildren)
	local children = inst:GetChildren()
	local n = { name = inst.Name, class = inst.ClassName, children_count = #children }
	if depth > 0 and #children > 0 then
		n.children = {}
		for i, child in ipairs(children) do
			if i > maxChildren then
				n.truncated = true
				break
			end
			table.insert(n.children, node(child, depth - 1, maxChildren))
		end
	end
	return n
end

function tools.get_explorer_tree(args)
	local depth = math.clamp(tonumber(args.depth) or 2, 1, 5)
	local maxChildren = tonumber(args.max_children) or 40
	if args.path == nil or args.path == "" or args.path == "game" then
		local out = {}
		for _, name in ipairs(TOP_LEVEL) do
			local ok, svc = pcall(game.GetService, game, name)
			if ok and svc then
				table.insert(out, node(svc, depth - 1, maxChildren))
			end
		end
		return { place = game.Name, services = out }
	end
	local inst = resolve(args.path)
	local tree = node(inst, depth, maxChildren)
	tree.path = pathOf(inst)
	return tree
end

function tools.find_instances(args)
	local root = resolve(args.root)
	local query = args.query and string.lower(args.query) or nil
	local className = args.class_name
	local limit = tonumber(args.limit) or 50
	local out = {}
	local descendants = {}
	if root == game then
		-- Some services can't be walked by plugins; search the usual ones.
		for _, name in ipairs(TOP_LEVEL) do
			local ok, svc = pcall(game.GetService, game, name)
			if ok and svc then
				for _, d in ipairs(svc:GetDescendants()) do
					table.insert(descendants, d)
				end
			end
		end
	else
		descendants = root:GetDescendants()
	end
	for _, d in ipairs(descendants) do
		local ok, match = pcall(function()
			if className and className ~= "" and not d:IsA(className) then
				return false
			end
			if query and query ~= "" and not string.find(string.lower(d.Name), query, 1, true) then
				return false
			end
			return true
		end)
		if ok and match then
			table.insert(out, { path = pathOf(d), class = d.ClassName })
			if #out >= limit then
				break
			end
		end
	end
	return { count = #out, results = out }
end

function tools.get_properties(args)
	local inst = resolve(args.path)
	local names = args.properties
	if type(names) ~= "table" or #names == 0 then
		names = COMMON
	end
	local props = {}
	for _, name in ipairs(names) do
		local ok, v = pcall(function()
			return inst[name]
		end)
		if ok and v ~= nil and typeof(v) ~= "RBXScriptSignal" and typeof(v) ~= "function" then
			props[name] = serialize(v)
		end
	end
	local attrs = {}
	for k, v in pairs(inst:GetAttributes()) do
		attrs[k] = serialize(v)
	end
	local out = { path = pathOf(inst), class = inst.ClassName, properties = props, attributes = attrs }
	out.children_count = #inst:GetChildren()
	if inst:IsA("LuaSourceContainer") then
		local _, lines = string.gsub(inst.Source, "\n", "")
		out.source_lines = lines + 1
	end
	return out
end

function tools.get_selection()
	local out = {}
	for _, inst in ipairs(Selection:Get()) do
		table.insert(out, { path = pathOf(inst), class = inst.ClassName })
	end
	return { selection = out }
end

function tools.set_selection(args)
	local list = {}
	for _, p in ipairs(args.paths or {}) do
		table.insert(list, resolve(p))
	end
	Selection:Set(list)
	return { selected = #list }
end

function tools.read_script(args)
	local inst = resolve(args.path)
	if not inst:IsA("LuaSourceContainer") then
		error(pathOf(inst) .. " is a " .. inst.ClassName .. ", not a script", 0)
	end
	local source = inst.Source
	pcall(function()
		local doc = ScriptEditorService:FindScriptDocument(inst)
		if doc then
			source = doc:GetText()
		end
	end)
	return { path = pathOf(inst), class = inst.ClassName, source = source }
end

function tools.get_output_log(args)
	local limit = tonumber(args.limit) or 50
	local history = LogService:GetLogHistory()
	local out = {}
	for i = math.max(1, #history - limit + 1), #history do
		local entry = history[i]
		local kind = tostring(entry.messageType):gsub("Enum.MessageType.Message", "")
		table.insert(out, string.format("[%s] %s", kind, entry.message))
	end
	return { lines = out }
end

function tools.create_instance(args)
	return withHistory("create " .. tostring(args.class_name), function()
		local inst = Instance.new(args.class_name)
		if args.name then
			inst.Name = args.name
		end
		local errors, parentOverride = setProps(inst, args.properties)
		if args.source and inst:IsA("LuaSourceContainer") then
			inst.Source = args.source
		end
		inst.Parent = parentOverride or resolve(args.parent)
		Selection:Set({ inst })
		return { path = pathOf(inst), class = inst.ClassName, errors = errors }
	end)
end

function tools.set_properties(args)
	local inst = resolve(args.path)
	return withHistory("edit " .. inst.Name, function()
		local errors, parent = setProps(inst, args.properties)
		if parent then
			inst.Parent = parent
		end
		return { path = pathOf(inst), errors = errors }
	end)
end

function tools.write_script(args)
	if type(args.source) ~= "string" then
		error("source is required", 0)
	end
	return withHistory("write " .. tostring(args.path), function()
		local ok, inst = pcall(resolve, args.path)
		local created = false
		if not ok then
			local parentPath, name = string.match(args.path, "^(.*)[%./]([^%./]+)$")
			if not parentPath then
				error("Give a full path like ServerScriptService.MyScript", 0)
			end
			inst = Instance.new(args.class_name or "Script")
			inst.Name = name
			inst.Parent = resolve(parentPath)
			created = true
		end
		if not inst:IsA("LuaSourceContainer") then
			error(pathOf(inst) .. " is a " .. inst.ClassName .. ", not a script", 0)
		end
		setSource(inst, args.source)
		local _, lines = string.gsub(args.source, "\n", "")
		return { path = pathOf(inst), class = inst.ClassName, created = created, lines = lines + 1 }
	end)
end

function tools.delete_instance(args)
	local inst = resolve(args.path)
	if inst == game or inst.Parent == game then
		error("Refusing to delete a service", 0)
	end
	local p = pathOf(inst)
	return withHistory("delete " .. inst.Name, function()
		inst.Parent = nil -- undoable, unlike Destroy()
		return { deleted = p }
	end)
end

function tools.run_code(args)
	local fn, compileErr = loadstring(args.code or "")
	if not fn then
		error("Compile error: " .. tostring(compileErr), 0)
	end
	local output = {}
	local function capture(prefix)
		return function(...)
			local parts = {}
			for i = 1, select("#", ...) do
				parts[i] = tostring((select(i, ...)))
			end
			table.insert(output, prefix .. table.concat(parts, " "))
		end
	end
	local env = setmetatable({ print = capture(""), warn = capture("[warn] ") }, { __index = getfenv(1) })
	setfenv(fn, env)
	return withHistory("run code", function()
		local results = table.pack(pcall(fn))
		if not results[1] then
			error("Runtime error: " .. tostring(results[2]) .. (#output > 0 and ("\nOutput:\n" .. table.concat(output, "\n")) or ""), 0)
		end
		local returned = {}
		for i = 2, results.n do
			table.insert(returned, serialize(results[i]))
		end
		return { output = output, returned = returned }
	end)
end

------------------------------------------------------------------------
-- Connection loop
------------------------------------------------------------------------

local function request(method, path, body)
	return HttpService:RequestAsync({
		Url = BASE .. path,
		Method = method,
		Headers = {
			["Content-Type"] = "application/json",
			["X-Blox-Bridge"] = "1",
			["X-Blox-Place"] = HttpService:UrlEncode(game.Name),
			["X-Blox-Plugin"] = VERSION,
		},
		Body = body and HttpService:JSONEncode(body) or nil,
	})
end

local lastReason = nil

local function setConnected(value)
	if connected ~= value then
		connected = value
		if value then
			lastReason = nil
			print("[Blox Bridge] Connected to the app on port " .. PORT)
		else
			print("[Blox Bridge] Waiting for the Blox Bridge app…")
		end
	end
end

local function execute(cmd)
	local handler = tools[cmd.tool]
	if not handler then
		return { id = cmd.id, ok = false, error = "Unknown tool " .. tostring(cmd.tool) }
	end
	local ok, result = pcall(handler, cmd.args or {})
	if ok then
		-- Make sure it can be encoded before sending.
		local encOk = pcall(HttpService.JSONEncode, HttpService, result)
		if not encOk then
			result = { value = tostring(result) }
		end
		return { id = cmd.id, ok = true, result = result }
	end
	return { id = cmd.id, ok = false, error = tostring(result) }
end

-- Explain a failed request once per distinct reason, so the Output window says what to fix.
local function explainFailure(ok, res)
	local reason
	if ok then
		reason = "HTTP " .. tostring(res.StatusCode) .. " from the app"
	else
		local msg = tostring(res)
		if msg:find("ConnectFail") or msg:find("refused") or msg:find("HttpError") then
			reason = "Can't reach the Blox Bridge app on 127.0.0.1:" .. PORT .. ". Is the app open?"
		elseif msg:lower():find("not enabled") or msg:lower():find("permission") or msg:lower():find("denied") then
			reason = "Studio blocked the connection. Open Plugins > Manage Plugins, find Blox Bridge and allow 127.0.0.1, then click Connect again. ("
				.. msg
				.. ")"
		else
			reason = msg
		end
	end
	if reason ~= lastReason then
		lastReason = reason
		warn("[Blox Bridge] " .. reason)
	end
end

local function loop(gen)
	while enabled and gen == generation do
		local ok, res = pcall(request, "GET", "/poll")
		if gen ~= generation then
			break
		end
		if not ok or not res.Success then
			setConnected(false)
			explainFailure(ok, res)
			task.wait(3)
		elseif res.StatusCode == 200 then
			setConnected(true)
			local decodeOk, cmd = pcall(HttpService.JSONDecode, HttpService, res.Body)
			if decodeOk and type(cmd) == "table" then
				local result = execute(cmd)
				pcall(request, "POST", "/result", result)
			end
		else
			setConnected(true)
		end
	end
end

local function start()
	generation += 1
	button:SetActive(enabled)
	if enabled then
		print("[Blox Bridge] v" .. VERSION .. " connecting to the Blox Bridge app on 127.0.0.1:" .. PORT .. "…")
		task.spawn(loop, generation)
	else
		setConnected(false)
		print("[Blox Bridge] Disconnected")
	end
end

button.Click:Connect(function()
	enabled = not enabled
	plugin:SetSetting(SETTING, enabled)
	start()
end)

plugin.Unloading:Connect(function()
	generation += 1
end)

start()
