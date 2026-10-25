--[[
  PrizeWheel_Setup.lua  -  run once in the Studio command bar / as a plugin script
  after importing out/PrizeWheel.glb with the 3D Importer (Asset Manager > Bulk Import).

  What it does
    * applies Roblox Materials / colours / reflectance to every MeshPart by name
    * anchors Base, welds Wheel + Pointer parts to their own root so they animate independently
    * returns a PrizeWheel module-style table with :Spin(segmentIndex) and :Flick()

  Assumes the imported model is named "PrizeWheel" in Workspace and that the wheel's
  front is the face the pointer sits on. If the wheel spins about the wrong axis after
  import, change WHEEL_AXIS below.
]]
local TweenService = game:GetService("TweenService")
local WHEEL_AXIS = Vector3.new(0, 0, 1)   -- wheel local spin axis (Z)
local SEGMENTS = 10

local model = workspace:WaitForChild("PrizeWheel")

local PAINT = {
	Base_Body    = {Enum.Material.SmoothPlastic, "E6EAF4", 0.15},
	Wheel_Rim    = {Enum.Material.SmoothPlastic, "E6EAF4", 0.15},
	Base_Metal   = {Enum.Material.Metal,         "3B404C", 0.25},
	Wheel_Frame  = {Enum.Material.Metal,         "3B404C", 0.25},
	Pointer_Pivot= {Enum.Material.Metal,         "3B404C", 0.25},
	Base_Accent  = {Enum.Material.SmoothPlastic, "4A3DFF", 0.35},
	Wheel_Accent = {Enum.Material.SmoothPlastic, "4A3DFF", 0.35},
	Pointer_Body = {Enum.Material.SmoothPlastic, "FF4D5E", 0.3},
	Pointer_Core = {Enum.Material.Neon,          "FFF2D6", 0},
	Base_LED     = {Enum.Material.Neon,          "00C8FF", 0},
	Wheel_LED    = {Enum.Material.Neon,          "00C8FF", 0},
	Hub_Core     = {Enum.Material.Neon,          "00C8FF", 0},
	Base_Glass   = {Enum.Material.Glass,         "BDEFFF", 0.1, 0.55},
	Hub_Glass    = {Enum.Material.Glass,         "BDEFFF", 0.1, 0.55},
}
local SEG_COLORS = {"E8344E", "F59E0B", "12B76A", "1496F2", "8B3DFF"}
local GEM_COLORS = {"FF6B80", "FFC23D", "4DEB9C", "4DB8FF", "B77DFF"}

local function apply(part, mat, hex, refl, transp)
	part.Material = mat
	part.Color = Color3.fromHex(hex)
	part.Reflectance = refl or 0
	part.Transparency = transp or 0
	part.CastShadow = mat ~= Enum.Material.Glass
end

for _, p in model:GetDescendants() do
	if p:IsA("BasePart") then
		local seg = p.Name:match("^Segment_(%d+)$")
		local gem = p.Name:match("^SegmentGem_(%d+)$")
		if seg then
			apply(p, Enum.Material.SmoothPlastic, SEG_COLORS[(tonumber(seg) - 1) % 5 + 1], 0.1)
		elseif gem then
			apply(p, Enum.Material.Neon, GEM_COLORS[(tonumber(gem) - 1) % 5 + 1], 0, 0.1)
		elseif PAINT[p.Name] then
			local c = PAINT[p.Name]
			apply(p, c[1], c[2], c[3], c[4])
		end
		p.CanCollide = false
		p.CanQuery = false
		p.CanTouch = false
	end
end

-- roots: Base is anchored; Wheel/Pointer roots are anchored and drive their welded children
local base, wheel, pointer = model.Base, model.Wheel, model.Pointer
base.Base_Body.CanCollide = true; base.Base_Metal.CanCollide = true

local function weldTo(root, folder)
	for _, p in folder:GetDescendants() do
		if p:IsA("BasePart") and p ~= root then
			p.Anchored = false
			local w = Instance.new("WeldConstraint")
			w.Part0, w.Part1, w.Parent = root, p, p
		end
	end
	root.Anchored = true
end
for _, p in base:GetDescendants() do if p:IsA("BasePart") then p.Anchored = true end end
-- Wheel_Rim is symmetric about the axle, so its pivot sits on the hub centre
local wheelRoot, pointerRoot = wheel.Wheel_Rim, pointer.Pointer_Pivot
weldTo(wheelRoot, wheel)
weldTo(pointerRoot, pointer)

local wheelHome, pointerHome = wheelRoot.CFrame, pointerRoot.CFrame
local angle = 0
local function setWheel(a)
	angle = a
	wheelRoot.CFrame = wheelHome * CFrame.fromAxisAngle(WHEEL_AXIS, math.rad(a))
end

local PrizeWheel = {}

--- Spin so segment `index` (1..10, 1 = top at rest) stops under the pointer.
function PrizeWheel:Spin(index, duration)
	duration = duration or 5
	local step = 360 / SEGMENTS
	local final = ((index - 1) * step) % 360                 -- rotate segment `index` (numbered clockwise) to 12 o'clock
	local target = angle - (angle % 360) + 360 * 5 + final   -- 5 extra full turns
	local v = Instance.new("NumberValue")
	v.Value = angle
	v.Changed:Connect(setWheel)
	local t = TweenService:Create(v, TweenInfo.new(duration, Enum.EasingStyle.Quart, Enum.EasingDirection.Out), {Value = target})
	t:Play(); t.Completed:Wait(); v:Destroy()
	self:Flick()
end

--- Little pointer kick (call on every segment boundary for a ticking effect).
function PrizeWheel:Flick()
	local kick = TweenService:Create(pointerRoot, TweenInfo.new(0.08, Enum.EasingStyle.Sine, Enum.EasingDirection.Out, 0, true),
		{CFrame = pointerHome * CFrame.Angles(0, 0, math.rad(18))})
	kick:Play()
end

return PrizeWheel
