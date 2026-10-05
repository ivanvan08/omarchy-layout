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
--
-- Manual resizing: the compositor does not resize tiled windows for a custom layout, the provider
-- does. `target.box` carries the current geometry, so a box that differs from the one this module
-- placed is read as a manual resize and is turned into a new split ratio, which is how dragging a
-- border shrinks the neighbour the way dwindle does. Single-window workspaces have no split to
-- adjust, so there the manual box is kept verbatim.

local STATE_DIR = os.getenv("OMARCHY_LAYOUT_STATE") or (os.getenv("HOME") .. "/.local/state/omarchy/layout")
local PROFILE_PATH = STATE_DIR .. "/profile.lua"
local LAYOUT_NAME = "omarchy-layout"
local LAYOUT_REF = "lua:" .. LAYOUT_NAME
local EPSILON = 2

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

-- Diagnostics are off unless the file exists (`touch /tmp/omarchy-layout-debug.log`). Lua `print` from
-- the config state does not reach the compositor log, so this file is the only channel for it.
local DEBUG_PATH = "/tmp/omarchy-layout-debug.log"
local debug_on = nil

local function dbg(fmt, ...)
  if debug_on == nil then
    local probe = io.open(DEBUG_PATH, "r")
    debug_on = probe ~= nil
    if probe then
      probe:close()
    end
  end
  if not debug_on then
    return
  end
  local handle = io.open(DEBUG_PATH, "a")
  if not handle then
    return
  end
  local ok, text = pcall(string.format, fmt, ...)
  handle:write(tostring(ok and text or fmt), "\n")
  handle:close()
end

local function box_differs(a, b)
  if not a or not b then
    return false
  end
  return math.abs((a.x or 0) - (b.x or 0)) > EPSILON
    or math.abs((a.y or 0) - (b.y or 0)) > EPSILON
    or math.abs((a.w or 0) - (b.w or 0)) > EPSILON
    or math.abs((a.h or 0) - (b.h or 0)) > EPSILON
end

local function clamp(value, low, high)
  if value < low then
    return low
  end
  if value > high then
    return high
  end
  return value
end

-- Manual geometry the user created, keyed by a stable path so it survives windows opening and
-- closing: ratios[path][child] changes a split, boxes[path] pins a leaf that has no split to change.
local manual = { ratios = {}, boxes = {} }
-- Key -> box this module last placed, so a different box can be recognised as a manual change.
local placed_box = {}
-- Target -> where it came from in the tree, for the next recalculation to attribute a change.
local origin = {}
-- The work area the manual geometry was measured against; a different area invalidates it.
local last_area = nil
-- The window set the last placement was computed for. A change here re-lays the workspace out
-- legitimately, so boxes that differ are the layout's own doing, not a manual resize.
local last_signature = nil

local function signature(ctx)
  local parts = {}
  for i, target in ipairs(ctx.targets) do
    local window = target.window
    parts[i] = (window and window.class) or "?"
  end
  return table.concat(parts, ",")
end

local function target_key(workspace, target)
  -- `index` is the host's stable slot for the target; the class is the fallback for a host that does
  -- not expose it yet. Keys must never collide, or one window's box would be read as another's.
  local slot = target.index
  if slot == nil then
    local window = target.window
    slot = (window and window.class) or "?"
  end
  return string.format("%s#%s", tostring(workspace), tostring(slot))
end

-- Places the leaf whose class matches an unplaced target into `box`.
-- `owner` describes the split this box came from, which is what a manual resize changes; it is nil
-- for a workspace whose tree is a single leaf, where there is no split to adjust.
-- A leaf with no matching window leaves its box free, so an unrelated window can use it.
local function place_node(ctx, node, path, box, used, free, owner)
  if node.class then
    for _, target in ipairs(ctx.targets) do
      local window = target.window
      if window and not used[target] and window.class == node.class then
        local pinned = manual.boxes[path]
        if pinned then
          target:set_box(pinned)
          dbg("[leaf] %s PINNED %d,%d %dx%d", path, pinned.x, pinned.y, pinned.w, pinned.h)
          origin[target] = { path = path, box = pinned, split = owner }
        else
          target:place(box)
          dbg("[leaf] %s box=%d,%d %dx%d owner=%s/%s", path, box.x, box.y, box.w, box.h,
            owner and owner.path or "-", owner and tostring(owner.child) or "-")
          origin[target] = { path = path, box = box, split = owner }
        end
        used[target] = true
        return
      end
    end
    free[#free + 1] = { path = path, box = box, split = owner }
    return
  end

  local children = node.children or {}
  local count = #children
  if count == 0 then
    free[#free + 1] = { path = path, box = box, split = owner }
    return
  end

  local ratios = node.ratios or {}
  local overrides = manual.ratios[path] or {}
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
      local share = overrides[i] or fraction
      -- `split(box, side, ratio)` cuts the axis at `ratio` and returns the `side` of the cut, so both
      -- halves are asked for with the same ratio. Passing `1 - ratio` for the second half is only
      -- correct at 0.5 and silently wrong for every other split.
      part = ctx:split(rest, vertical and "top" or "left", share)
      remaining = ctx:split(rest, vertical and "bottom" or "right", share)
    else
      part = rest
      remaining = nil
    end

    local child_path = string.format("%s/%d", path, i)
    place_node(ctx, children[i], child_path, part, used, free, {
      path = path,
      child = i,
      rest = rest,
      vertical = vertical,
    })

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

-- Reads a box the user produced and turns it into a ratio for the split that owns it.
local function learn_manual_geometry(workspace, ctx)
  for _, target in ipairs(ctx.targets) do
    local key = target_key(workspace, target)
    local current = target.box
    local previous = placed_box[key]
    local trace = origin[target]
    if current and previous and box_differs(current, previous) and trace then
      if trace.split then
        local span = trace.split.vertical and (trace.split.rest.h or 0) or (trace.split.rest.w or 0)
        local got = trace.split.vertical and (current.h or 0) or (current.w or 0)
        if span > 0 then
          local share = clamp((got + 12) / (span + 12), 0.05, 0.95)
          manual.ratios[trace.split.path] = manual.ratios[trace.split.path] or {}
          manual.ratios[trace.split.path][trace.split.child] = share
        end
      else
        manual.boxes[trace.path] = { x = current.x, y = current.y, w = current.w, h = current.h }
      end
    end
  end
end

local function place_leftovers(ctx, placed, free)
  local pending = {}
  for _, target in ipairs(ctx.targets) do
    if not placed[target] and target.window then
      pending[#pending + 1] = target
    end
  end
  if #pending == 0 then
    return
  end

  local cell = 1
  local slot = free[cell]
  local total = #pending

  for i, target in ipairs(pending) do
    if not slot then
      return
    end
    local pending_left = total - i + 1
    local cells_left = #free - cell + 1
    local box = slot.box
    if pending_left > cells_left then
      local slots = pending_left - cells_left + 1
      target:place(ctx:split(box, "left", 1 / slots))
      box = ctx:split(box, "right", 1 / slots)
      slot.box = box
    else
      target:place(box)
      cell = cell + 1
      slot = free[cell]
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

  -- A workspace may opt out of the managed layout (`"layout": "dwindle"`), in which case this
  -- provider must keep its hands off it: Hyprland offers no resize hook for a custom layout, and a
  -- workspace where manual resizing matters belongs to a built-in one.
  if tree.layout then
    return
  end

  -- A different work area (monitor change, scaling) invalidates every manual ratio measured before.
  local area_changed = last_area and box_differs(last_area, ctx.area) or false
  if area_changed then
    manual.ratios, manual.boxes = {}, {}
  end
  last_area = { x = ctx.area.x, y = ctx.area.y, w = ctx.area.w, h = ctx.area.h }

  local current_signature = signature(ctx)
  if current_signature ~= last_signature then
    -- Windows appeared or disappeared: the workspace is being laid out again, and a pinned single
    -- window would now overlap its new neighbour. Split ratios survive, pins do not.
    manual.boxes = {}
  else
    learn_manual_geometry(workspace, ctx)
  end
  last_signature = current_signature

  local function show(box)
    return box and string.format("%d,%d %dx%d", box.x, box.y, box.w, box.h) or "nil"
  end
  dbg("[recalc] ws=%s area=%s targets=%d sig=%s", workspace, show(ctx.area), #ctx.targets, current_signature)
  for path, ratios in pairs(manual.ratios) do
    for child, share in pairs(ratios) do
      dbg("[recalc] override %s child %s = %.3f", path, tostring(child), share)
    end
  end
  for _, target in ipairs(ctx.targets) do
    local window = target.window
    dbg("[recalc]   target index=%s class=%s box=%s", tostring(target.index),
      window and tostring(window.class) or "nil", show(target.box))
  end

  origin = {}
  local used = {}
  local free = {}
  place_node(ctx, tree, "root", ctx.area, used, free)

  -- Record what this pass produced, so the next one can tell a manual change from its own output.
  for _, target in ipairs(ctx.targets) do
    local trace = origin[target]
    if trace then
      placed_box[target_key(workspace, target)] = trace.box
    end
  end

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
    place_node(ctx, tree, "root", left, used, free)
    free[#free + 1] = { path = "leftover", box = right }
    for _, target in ipairs(ctx.targets) do
      local trace = origin[target]
      if trace then
        placed_box[target_key(workspace, target)] = trace.box
      end
    end
  end

  place_leftovers(ctx, used, free)
end

-- Guarded: a config reload re-runs this file, and a duplicate registration must not surface as an
-- error overlay. Registration is by name, so re-running it is harmless.
pcall(hl.layout.register, LAYOUT_NAME, {
  recalculate = recalculate,
  -- Resize and move intents would reach a custom layout as messages; none arrive on Hyprland 0.56.2.
  -- The diagnostics file records any that do.
  layout_msg = function(_ctx, msg)
    dbg("[layout_msg] %s", tostring(msg))
    return false
  end,
})

-- Wire the workspaces named by the profile so that a config reload is enough after an apply.
local profile = load_profile()
for workspace, node in pairs((profile or {}).workspaces or {}) do
  local layout = (node or {}).layout
  if not layout then
    layout = ((profile or {}).mode == "internal") and "scrolling" or LAYOUT_REF
  end
  hl.workspace_rule({ workspace = tostring(workspace), layout = layout })
end

-- Send every profile window to its workspace at map time. Launch-and-move from the CLI cannot do this
-- reliably: an app that shows a splash or updater window first (Discord) maps its real window much
-- later, on whatever workspace is current then. A compositor rule has no timing to lose.
-- `silent` keeps focus where the user is. Scratchpad entries get no rule: their class is shared with
-- every other window of the same terminal, which would all be dragged into the scratchpad.
-- A leaf can opt out with "rule": false.
local function regex_escape(text)
  return (text:gsub("[%^%$%(%)%.%[%]%*%+%-%?%{%}%|\\]", "\\%0"))
end

local function leaves_of(node, out)
  if node.class then
    out[#out + 1] = node
    return out
  end
  for _, child in ipairs(node.children or {}) do
    leaves_of(child, out)
  end
  return out
end

for workspace, node in pairs((profile or {}).workspaces or {}) do
  for _, leaf in ipairs(leaves_of(node or {}, {})) do
    if leaf.rule ~= false then
      pcall(hl.window_rule, {
        match = { class = "^" .. regex_escape(leaf.class) .. "$" },
        workspace = tostring(workspace) .. " silent",
      })
    end
  end
end
