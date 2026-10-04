-- omarchy-layout: place tiled windows into the cells defined by the compiled profile.
--
-- Source of truth is <repo>/profiles/windows.json, compiled by `omarchy-layout apply` into
-- ~/.local/state/omarchy/layout/profile.lua. This module reads that file on every recalculation,
-- so a new `apply` takes effect without a Hyprland config reload.
--
-- The layout is registered as `lua:omarchy-layout` and enabled per workspace. Workspaces named by
-- the profile get their rule here (at config load) and again from `omarchy-layout apply` (at runtime).
-- On the internal laptop panel the profile carries mode = "internal" and the workspaces use
-- Hyprland's built-in `scrolling` layout instead, with full-size windows.

local STATE_DIR = os.getenv("OMARCHY_LAYOUT_STATE") or (os.getenv("HOME") .. "/.local/state/omarchy/layout")
local PROFILE_PATH = STATE_DIR .. "/profile.lua"
local LAYOUT_NAME = "omarchy-layout"
local LAYOUT_REF = "lua:" .. LAYOUT_NAME

local function load_profile()
  local chunk = loadfile(PROFILE_PATH)
  if not chunk then
    return nil
  end
  local ok, data = pcall(chunk)
  if not ok or type(data) ~= "table" then
    return nil
  end
  return data
end

-- Places the leaf whose class matches an unplaced target into `box`.
-- A leaf with no matching window leaves its box free, so an unrelated window can use it.
local function place_node(ctx, node, box, used, free)
  if node.class then
    for _, target in ipairs(ctx.targets) do
      local window = target.window
      if window and not used[target] and window.class == node.class then
        target:place(box)
        used[target] = true
        return
      end
    end
    free[#free + 1] = box
    return
  end

  local children = node.children or {}
  local count = #children
  if count == 0 then
    free[#free + 1] = box
    return
  end

  local ratios = node.ratios or {}
  local vertical = node.split == "rows"
  local rest = box

  for i = 1, count do
    local fraction = 1 / (count - i + 1)
    if ratios[i] then
      local sum = 0
      for j = i, count do
        sum = sum + (ratios[j] or 0)
      end
      if sum > 0 then
        fraction = ratios[i] / sum
      end
    end

    local part, remaining
    if i < count then
      part = ctx:split(rest, vertical and "top" or "left", fraction)
      remaining = ctx:split(rest, vertical and "bottom" or "right", 1 - fraction)
    else
      part = rest
      remaining = nil
    end

    place_node(ctx, children[i], part, used, free)
    rest = remaining
  end
end

local function workspace_of(ctx)
  for _, target in ipairs(ctx.targets) do
    local window = target.window
    if window and window.workspace then
      return tostring(window.workspace.id)
    end
  end
  return nil
end

local function place_leftovers(ctx, targets, free)
  local pending = {}
  for _, target in ipairs(targets) do
    if not target.placed and target.window then
      pending[#pending + 1] = target
    end
  end
  if #pending == 0 then
    return
  end

  local cell = 1
  local box = free[cell]
  local total = #pending

  for i, target in ipairs(pending) do
    if not box then
      return
    end
    local pending_left = total - i + 1
    local cells_left = #free - cell + 1
    if pending_left > cells_left then
      local slots = pending_left - cells_left + 1
      target:place(ctx:split(box, "left", 1 / slots))
      box = ctx:split(box, "right", 1 - 1 / slots)
    else
      target:place(box)
      cell = cell + 1
      box = free[cell]
    end
  end
end

local function recalculate(ctx)
  local profile = load_profile()
  if not profile or profile.mode == "internal" then
    return
  end

  local workspace = workspace_of(ctx)
  if not workspace then
    return
  end

  local tree = (profile.workspaces or {})[workspace]
  if not tree then
    return
  end

  local used = {}
  local free = {}
  place_node(ctx, tree, ctx.area, used, free)

  local leftovers = {}
  for _, target in ipairs(ctx.targets) do
    if not used[target] and target.window then
      leftovers[#leftovers + 1] = target
    end
  end
  if #leftovers == 0 then
    return
  end

  if #free == 0 then
    -- Every profile cell is taken and there are more windows: halve the area, keep the profile
    -- tree on the left, give the right half to the extra windows.
    used = {}
    free = {}
    local left = ctx:split(ctx.area, "left", 0.5)
    local right = ctx:split(ctx.area, "right", 0.5)
    place_node(ctx, tree, left, used, free)
    free[#free + 1] = right
  end

  for _, target in ipairs(ctx.targets) do
    target.placed = used[target] == true
  end
  place_leftovers(ctx, ctx.targets, free)
end

hl.layout.register(LAYOUT_NAME, { recalculate = recalculate })

-- Wire the workspaces named by the profile so that a config reload is enough after an apply.
local profile = load_profile()
for workspace, _ in pairs((profile or {}).workspaces or {}) do
  local layout = ((profile or {}).mode == "internal") and "scrolling" or LAYOUT_REF
  hl.workspace_rule({ workspace = tostring(workspace), layout = layout })
end
