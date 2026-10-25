-- MotorcycleRig (ModuleScript)
-- Turns the imported MotorcycleTag_Bike model into a physics rig:
--   * body parts welded to Frame (Frame becomes the PrimaryPart)
--   * steering parts welded to Fork, Fork hinged to Frame on the raked steering axis (servo)
--   * FrontWheel hinged to Fork (free spin), RearWheel hinged to Swingarm (motor drive)
--   * an AlignOrientation that keeps the bike upright while leaving yaw free
--
-- Usage (server):
--   local MotorcycleRig = require(game.ServerStorage.MotorcycleRig)
--   local bike = game.ServerStorage.MotorcycleTag_Bike:Clone()
--   bike.Parent = workspace
--   MotorcycleRig.Rig(bike)            -- once, while the bike stands upright
--   MotorcycleRig.SetSteer(bike, 0.5)  -- -1 full left .. 1 full right
--   MotorcycleRig.SetThrottle(bike, 1) -- -1 reverse .. 1 full forward
--   MotorcycleRig.SetPaint(bike, Color3.fromRGB(40, 140, 255))  -- e.g. tint whoever is "it"
--
-- All joints sit on the wheel centres, so the rig works at any import scale.

local MotorcycleRig = {}

MotorcycleRig.RAKE = math.rad(24)   -- fork angle baked into the model
MotorcycleRig.STEER_LOCK = 30       -- degrees; the model is clearance-checked up to this
MotorcycleRig.WHEEL_SPEED = 60      -- rear wheel rad/s at full throttle
MotorcycleRig.DRIVE_TORQUE = 20000
MotorcycleRig.PAINT = Color3.fromRGB(242, 73, 46)

local BODY_PARTS = { "Bodywork", "Seat", "Engine", "Exhaust", "Swingarm", "TailLight" }
local STEER_PARTS = { "Handlebars", "FrontFender", "HeadlightCowl", "Headlight", "Windscreen" }
local PAINT_PARTS = { "Bodywork", "FrontFender", "HeadlightCowl" }

-- Parts listed with a colour lose the palette texture and use Color + Material instead.
local LOOK = {
	Frame = { Enum.Material.Metal },
	Fork = { Enum.Material.Metal },
	Swingarm = { Enum.Material.Metal },
	Engine = { Enum.Material.Metal },
	Exhaust = { Enum.Material.Metal },
	Headlight = { Enum.Material.Neon, Color3.fromRGB(225, 240, 255) },
	TailLight = { Enum.Material.Neon, Color3.fromRGB(255, 40, 55) },
	Windscreen = { Enum.Material.Glass, Color3.fromRGB(52, 62, 76), 0.35 },
}

local function getPart(model, name)
	local part = model:FindFirstChild(name, true)
	if not part or not part:IsA("BasePart") then
		error(("MotorcycleRig: %s has no part named %q"):format(model:GetFullName(), name), 3)
	end
	return part
end

local function useFlatColor(part, color)
	-- Clearing the palette texture lets Color show; imported textures may also arrive as a SurfaceAppearance.
	pcall(function()
		part.TextureID = ""
	end)
	local appearance = part:FindFirstChildOfClass("SurfaceAppearance")
	if appearance then
		appearance:Destroy()
	end
	part.Color = color
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

function MotorcycleRig.Rig(model)
	local frame = getPart(model, "Frame")
	local fork = getPart(model, "Fork")
	local swingarm = getPart(model, "Swingarm")
	local frontWheel = getPart(model, "FrontWheel")
	local rearWheel = getPart(model, "RearWheel")

	-- Derive the bike's axes from the wheels, so any import orientation or heading works.
	local flat = (frontWheel.Position - rearWheel.Position) * Vector3.new(1, 0, 1)
	local forward = flat.Unit
	local up = Vector3.yAxis
	local right = forward:Cross(up)
	local steerAxis = (up * math.cos(MotorcycleRig.RAKE) - forward * math.sin(MotorcycleRig.RAKE)).Unit

	model.PrimaryPart = frame
	for _, part in ipairs(model:GetDescendants()) do
		if part:IsA("BasePart") then
			part.Anchored = false
			-- Only the wheels touch the world; everything else still fires Touched for tagging.
			part.CanCollide = part == frontWheel or part == rearWheel
			part.CanTouch = true
		end
	end

	for _, name in ipairs(BODY_PARTS) do
		weld(frame, getPart(model, name))
	end
	for _, name in ipairs(STEER_PARTS) do
		weld(fork, getPart(model, name))
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
		local part = getPart(model, name)
		part.Material = look[1]
		if look[2] then
			useFlatColor(part, look[2])
		end
		if look[3] then
			part.Transparency = look[3]
		end
	end
	MotorcycleRig.SetPaint(model, MotorcycleRig.PAINT)
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

function MotorcycleRig.SetPaint(model, color)
	for _, name in ipairs(PAINT_PARTS) do
		local part = getPart(model, name)
		useFlatColor(part, color)
		part.Material = Enum.Material.SmoothPlastic
	end
end

return MotorcycleRig
