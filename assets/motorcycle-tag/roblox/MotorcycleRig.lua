-- MotorcycleRig (ModuleScript)
-- Turns an imported Motorcycle Tag bike (street bike, dirt bike, superbike, chopper, scooter, adventure,
-- electric, café racer or police bike) into a physics rig:
--   * every body part welded to Frame (Frame becomes the PrimaryPart)
--   * steering parts welded to Fork, Fork hinged to Frame on the raked steering axis (servo)
--   * FrontWheel hinged to Fork (free spin), RearWheel hinged to Swingarm (motor drive)
--   * an AlignOrientation that keeps the bike upright while leaving yaw free
--
-- Usage (server):
--   local MotorcycleRig = require(game.ServerStorage.MotorcycleRig)
--   local bike = game.ServerStorage.MotorcycleTag_DirtBike:Clone()
--   bike.Parent = workspace
--   MotorcycleRig.Rig(bike)            -- once, while the bike stands upright
--   MotorcycleRig.SetSteer(bike, 0.5)  -- -1 full left .. 1 full right
--   MotorcycleRig.SetThrottle(bike, 1) -- -1 reverse .. 1 full forward
--   MotorcycleRig.SetSkin(bike, "rbxassetid://123")             -- swap the whole skin texture
--   MotorcycleRig.SetHighlight(bike, Color3.fromRGB(255, 0, 0)) -- outline whoever is "it"; nil clears
--   MotorcycleRig.SetSirens(bike, true)  -- police bike: flash the red and blue lights (false stops)
--
-- All joints sit on the wheel centres, so the rig works at any import scale.

local MotorcycleRig = {}

MotorcycleRig.STEER_LOCK = 30       -- degrees; the models are clearance-checked up to this
MotorcycleRig.WHEEL_SPEED = 60      -- rear wheel rad/s at full throttle
MotorcycleRig.DRIVE_TORQUE = 20000

-- Fork angle (degrees from vertical) baked into each model. A model can also carry a
-- "SteeringRake" attribute, or Rig can be given { rake = degrees }.
MotorcycleRig.RAKE_BY_MODEL = {
	MotorcycleTag_Bike = 24,
	MotorcycleTag_DirtBike = 27,
	MotorcycleTag_SuperBike = 23,
	MotorcycleTag_Chopper = 34,
	MotorcycleTag_Scooter = 26,
	MotorcycleTag_Adventure = 26,
	MotorcycleTag_Electric = 24,
	MotorcycleTag_Cafe = 25,
	MotorcycleTag_Police = 26,
}

-- Parts that turn with the handlebars (whichever of them a model has). Everything else
-- except the wheels is welded to Frame, including the frame-mounted Headlights and
-- Windshield of the superbike, adventure and electric bikes.
local STEER_PARTS = { "Handlebars", "FrontFender", "HeadlightCowl", "Headlight", "Windscreen", "FrontPlate" }
-- The street bike's single-colour paint parts, recoloured by SetPaint.
local PAINT_PARTS = { "Bodywork", "FrontFender", "HeadlightCowl" }

-- Parts listed with a colour lose the texture and use Color + Material instead.
local LOOK = {
	Frame = { Enum.Material.Metal },
	Fork = { Enum.Material.Metal },
	Swingarm = { Enum.Material.Metal },
	Engine = { Enum.Material.Metal },
	Exhaust = { Enum.Material.Metal },
	Headlight = { Enum.Material.Neon, Color3.fromRGB(225, 240, 255) },
	Headlights = { Enum.Material.Neon, Color3.fromRGB(225, 240, 255) },
	TailLight = { Enum.Material.Neon, Color3.fromRGB(255, 40, 55) },
	Windscreen = { Enum.Material.Glass, Color3.fromRGB(52, 62, 76), 0.35 },
	Windshield = { Enum.Material.Glass, Color3.fromRGB(40, 52, 70), 0.35 },
	LightsRed = { Enum.Material.SmoothPlastic, Color3.fromRGB(255, 30, 40) }, -- unlit until SetSirens
	LightsBlue = { Enum.Material.SmoothPlastic, Color3.fromRGB(30, 80, 255) },
}

local function getPart(model, name)
	local part = model:FindFirstChild(name, true)
	if not part or not part:IsA("BasePart") then
		error(("MotorcycleRig: %s has no part named %q"):format(model:GetFullName(), name), 3)
	end
	return part
end

local function clearTexture(part)
	-- Imported textures may arrive as TextureID or as a SurfaceAppearance.
	pcall(function()
		part.TextureID = ""
	end)
	local appearance = part:FindFirstChildOfClass("SurfaceAppearance")
	if appearance then
		appearance:Destroy()
	end
end

local function weld(part0, part1)
	local w = Instance.new("WeldConstraint")
	w.Name = "Weld_" .. part1.Name
	w.Part0 = part0
	w.Part1 = part1
	w.Parent = part1
end

local function attachment(part, name, worldCFrame)
	local a = Instance.new("Attachment")
	a.Name = name
	a.Parent = part
	a.WorldCFrame = worldCFrame
	return a
end

-- A HingeConstraint spins around the attachments' X axis, so worldCFrame.RightVector is the axle.
local function hinge(name, part0, part1, worldCFrame)
	local h = Instance.new("HingeConstraint")
	h.Name = name
	h.Attachment0 = attachment(part0, name .. "0", worldCFrame)
	h.Attachment1 = attachment(part1, name .. "1", worldCFrame)
	h.Parent = part0
	return h
end

local function rakeFor(model, options)
	local rake = (options and options.rake) or model:GetAttribute("SteeringRake") or MotorcycleRig.RAKE_BY_MODEL[model.Name]
	if not rake then
		warn(("MotorcycleRig: no rake known for %s, assuming 24 degrees"):format(model.Name))
		rake = 24
	end
	return math.rad(rake)
end

-- options (optional): { rake = degrees }
function MotorcycleRig.Rig(model, options)
	local frame = getPart(model, "Frame")
	local fork = getPart(model, "Fork")
	local swingarm = getPart(model, "Swingarm")
	local frontWheel = getPart(model, "FrontWheel")
	local rearWheel = getPart(model, "RearWheel")
	local rake = rakeFor(model, options)

	-- Derive the bike's axes from the wheels, so any import orientation or heading works.
	local flat = (frontWheel.Position - rearWheel.Position) * Vector3.new(1, 0, 1)
	local forward = flat.Unit
	local up = Vector3.yAxis
	local right = forward:Cross(up)
	local steerAxis = (up * math.cos(rake) - forward * math.sin(rake)).Unit

	local steering = {}
	for _, name in ipairs(STEER_PARTS) do
		steering[name] = true
	end

	model.PrimaryPart = frame
	for _, part in ipairs(model:GetDescendants()) do
		if part:IsA("BasePart") then
			part.Anchored = false
			-- Only the wheels touch the world; everything else still fires Touched for tagging.
			part.CanCollide = part == frontWheel or part == rearWheel
			part.CanTouch = true
			if steering[part.Name] then
				weld(fork, part)
			elseif part ~= frame and part ~= fork and part ~= frontWheel and part ~= rearWheel then
				weld(frame, part)
			end
		end
	end

	-- The steering axis passes through the front axle, so the joint sits on the wheel centre.
	local steer = hinge("SteerHinge", frame, fork, CFrame.fromMatrix(frontWheel.Position, steerAxis, right))
	steer.ActuatorType = Enum.ActuatorType.Servo
	steer.ServoMaxTorque = 1e6
	steer.AngularSpeed = math.rad(360)
	steer.LimitsEnabled = true
	steer.LowerAngle = -MotorcycleRig.STEER_LOCK
	steer.UpperAngle = MotorcycleRig.STEER_LOCK

	hinge("FrontWheelHinge", fork, frontWheel, CFrame.fromMatrix(frontWheel.Position, right, up))

	local drive = hinge("RearWheelHinge", swingarm, rearWheel, CFrame.fromMatrix(rearWheel.Position, right, up))
	drive.ActuatorType = Enum.ActuatorType.Motor
	drive.MotorMaxTorque = MotorcycleRig.DRIVE_TORQUE
	drive.AngularVelocity = 0

	local upright = Instance.new("AlignOrientation")
	upright.Name = "KeepUpright"
	upright.Mode = Enum.OrientationAlignmentMode.OneAttachment
	upright.AlignType = Enum.AlignType.PrimaryAxisParallel
	upright.Attachment0 = attachment(frame, "UprightAttachment", CFrame.fromMatrix(frame.Position, up, right))
	upright.PrimaryAxis = Vector3.yAxis
	upright.MaxTorque = 1e6
	upright.Responsiveness = 25
	upright.Parent = frame

	for name, look in pairs(LOOK) do
		local part = model:FindFirstChild(name, true)
		if part and part:IsA("BasePart") then
			part.Material = look[1]
			if look[2] then
				clearTexture(part)
				part.Color = look[2]
			end
			if look[3] then
				part.Transparency = look[3]
			end
		end
	end
	return model
end

-- amount: -1 (full left) .. 1 (full right)
function MotorcycleRig.SetSteer(model, amount)
	local steer = getPart(model, "Frame"):FindFirstChild("SteerHinge")
	-- A positive hinge angle turns counter-clockwise seen from above (left), hence the minus.
	steer.TargetAngle = -math.clamp(amount, -1, 1) * MotorcycleRig.STEER_LOCK
end

-- amount: -1 (reverse) .. 1 (full forward)
function MotorcycleRig.SetThrottle(model, amount)
	local drive = getPart(model, "Swingarm"):FindFirstChild("RearWheelHinge")
	-- Rolling forward is a negative spin about the bike's right axis.
	drive.AngularVelocity = -math.clamp(amount, -1, 1) * MotorcycleRig.WHEEL_SPEED
end

-- Applies one skin texture to every textured part. Lights and glass keep their flat look.
function MotorcycleRig.SetSkin(model, textureId)
	for _, part in ipairs(model:GetDescendants()) do
		local look = LOOK[part.Name]
		if part:IsA("MeshPart") and not (look and look[2]) then
			local appearance = part:FindFirstChildOfClass("SurfaceAppearance")
			if appearance then
				appearance:Destroy()
			end
			part.TextureID = textureId
		end
	end
end

-- Police bike: alternately flashes the LightsRed and LightsBlue parts until called with false.
-- Call it once the bike is in the workspace; the flashing stops by itself if the bike is removed.
function MotorcycleRig.SetSirens(model, on)
	model:SetAttribute("SirensOn", on == true)
	local red = model:FindFirstChild("LightsRed", true)
	local blue = model:FindFirstChild("LightsBlue", true)
	if not (on and red and blue) or model:GetAttribute("SirensRunning") then
		return
	end
	model:SetAttribute("SirensRunning", true)
	task.spawn(function()
		local phase = false
		while model:IsDescendantOf(game) and model:GetAttribute("SirensOn") do
			phase = not phase
			red.Material = phase and Enum.Material.Neon or Enum.Material.SmoothPlastic
			blue.Material = phase and Enum.Material.SmoothPlastic or Enum.Material.Neon
			task.wait(0.25)
		end
		red.Material = Enum.Material.SmoothPlastic
		blue.Material = Enum.Material.SmoothPlastic
		model:SetAttribute("SirensRunning", false)
	end)
end

-- Outlines the whole bike (e.g. the player who is "it"); pass nil to remove.
function MotorcycleRig.SetHighlight(model, color)
	local highlight = model:FindFirstChild("TagHighlight")
	if not color then
		if highlight then
			highlight:Destroy()
		end
		return
	end
	if not highlight then
		highlight = Instance.new("Highlight")
		highlight.Name = "TagHighlight"
		highlight.DepthMode = Enum.HighlightDepthMode.Occluded
		highlight.Parent = model
	end
	highlight.OutlineColor = color
	highlight.FillColor = color
	highlight.FillTransparency = 0.75
end

-- Street bike only: recolours its single-colour paint parts.
function MotorcycleRig.SetPaint(model, color)
	for _, name in ipairs(PAINT_PARTS) do
		local part = getPart(model, name)
		clearTexture(part)
		part.Color = color
		part.Material = Enum.Material.SmoothPlastic
	end
end

return MotorcycleRig
