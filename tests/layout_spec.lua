-- Hermetic check of the cell arithmetic in hypr/omarchy-layout.lua.
--
-- Fakes the compositor side (work area, target list, ctx:split, target:place) and runs the real
-- layout provider against a fixture profile, so the placement rules are verified without a session.
--
-- Run with a private state dir, the test writes the fixture into it:
--   OMARCHY_LAYOUT_STATE=$(mktemp -d) lua5.4 tests/layout_spec.lua

local state_dir = os.getenv("OMARCHY_LAYOUT_STATE")
if not state_dir then
  io.stderr:write("set OMARCHY_LAYOUT_STATE to a scratch directory; refusing to use the live state\n")
  os.exit(2)
end

local module_path = os.getenv("OMARCHY_LAYOUT_MODULE")
if not module_path then
  local self = debug.getinfo(1, "S").source:sub(2)
  module_path = self:gsub("tests/layout_spec%.lua$", "hypr/omarchy-layout.lua")
end

-- Fixture: the documented schema, one leaf workspace, one nested workspace, a scratchpad entry.
local fixture = [[
return {
  ["version"] = 1,
  ["mode"] = "external",
  ["scratchpad"] = { { ["app"] = "herdr", ["class"] = "com.mitchellh.ghostty" } },
  ["workspaces"] = {
    ["1"] = { ["app"] = "brave", ["class"] = "brave-origin" },
    ["2"] = {
      ["split"] = "columns",
      ["ratios"] = { 0.5, 0.5 },
      ["children"] = {
        { ["split"] = "columns", ["ratios"] = { 0.5, 0.5 }, ["children"] = {
          { ["app"] = "signal", ["class"] = "signal" },
          { ["app"] = "telegram", ["class"] = "org.telegram.desktop" },
        } },
        { ["app"] = "discord", ["class"] = "discord" },
      },
    },
  },
}
]]

local handle = assert(io.open(state_dir .. "/profile.lua", "w"))
handle:write(fixture)
handle:close()

local GAP = 12
local AREA = { x = 12, y = 42, w = 3176, h = 846 }
local registered, rules = nil, {}

hl = {
  layout = { register = function(_name, provider) registered = provider end },
  workspace_rule = function(spec) rules[#rules + 1] = spec end,
}

dofile(module_path)
assert(registered and registered.recalculate, "layout was not registered")

-- The compositor subtracts the gap from the ratio share of a split.
local function split(box, side, ratio)
  local x, y, w, h = box.x, box.y, box.w, box.h
  if side == "left" or side == "right" then
    local part = math.floor(ratio * (w + GAP) + 0.5) - GAP
    if side == "left" then
      return { x = x, y = y, w = part, h = h }
    end
    return { x = x + part + GAP, y = y, w = w - part - GAP, h = h }
  end
  local part = math.floor(ratio * (h + GAP) + 0.5) - GAP
  if side == "top" then
    return { x = x, y = y, w = w, h = part }
  end
  return { x = x, y = y + part + GAP, w = w, h = h - part - GAP }
end

local function run(classes, workspace)
  local placed = {}
  local ctx = { area = AREA, targets = {} }
  ctx.split = function(_, box, side, ratio)
    return split(box, side, ratio)
  end
  for _, klass in ipairs(classes) do
    ctx.targets[#ctx.targets + 1] = {
      window = { class = klass, workspace = { id = workspace } },
      place = function(_, box)
        placed[klass] = box
      end,
    }
  end
  registered.recalculate(ctx)
  return placed
end

local function fmt(box)
  return box and string.format("%d,%d %dx%d", box.x, box.y, box.w, box.h) or nil
end

local fails = 0
local function check(label, got, want)
  if got ~= want then
    fails = fails + 1
  end
  print(string.format("%-34s %s  got=%-18s want=%s", label, got == want and "PASS" or "FAIL", got or "-", want or "-"))
end

local nested = run({ "signal", "org.telegram.desktop", "discord" }, 2)
check("nested ws2 signal", fmt(nested["signal"]), "12,42 785x846")
check("nested ws2 telegram", fmt(nested["org.telegram.desktop"]), "809,42 785x846")
check("nested ws2 discord", fmt(nested["discord"]), "1606,42 1582x846")

local single = run({ "brave-origin" }, 1)
check("single window fills area", fmt(single["brave-origin"]), "12,42 3176x846")

local extra = run({ "signal", "org.telegram.desktop", "discord", "foot" }, 2)
print("window outside the profile:")
for _, klass in ipairs({ "signal", "org.telegram.desktop", "discord", "foot" }) do
  print("   " .. klass .. " -> " .. (fmt(extra[klass]) or "NOT PLACED"))
end
check("outside window is placed", tostring(extra["foot"] ~= nil), "true")
check("outside window takes the right half", tostring(extra["foot"] ~= nil and extra["foot"].x > 1600), "true")
check("profile windows keep their order", tostring(extra["signal"] ~= nil and extra["signal"].x == 12), "true")

local partial = run({ "signal", "discord" }, 2)
check("missing app keeps its cell free", fmt(partial["signal"]), "12,42 785x846")
check("missing app does not shift others", fmt(partial["discord"]), "1606,42 1582x846")

check("empty workspace is a no-op", tostring(next(run({}, 2))), "nil")

local layouts = {}
for _, rule in ipairs(rules) do
  layouts[tostring(rule.workspace)] = rule.layout
end
check("rules registered", tostring(#rules), "2")
check("rule ws 1", layouts["1"], "lua:omarchy-layout")
check("rule ws 2", layouts["2"], "lua:omarchy-layout")

print(fails == 0 and "ALL PASS" or (fails .. " FAILURES"))
os.exit(fails == 0 and 0 or 1)
