-- Hermetic check of the placement rules in hypr/omarchy-layout.lua.
--
-- Fakes the compositor side (work area, target list, ctx:split, target:place) and runs the real
-- layout provider against a fixture profile, so the placement rules are verified without a session.
-- The fixture uses synthetic app names and an arbitrary work area: nothing here depends on the
-- machine the test runs on, and no personal setup is baked in.
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

local GAP = 12
local BAR = 30
local SCREEN = { w = 1200, h = 720 }
local AREA = { x = GAP, y = BAR + GAP, w = SCREEN.w - 2 * GAP, h = SCREEN.h - BAR - 2 * GAP }

-- Fixture: the documented schema, one leaf workspace, one nested workspace, a scratchpad entry.
local fixture = [[
return {
  ["version"] = 1,
  ["mode"] = "external",
  ["scratchpad"] = { { ["app"] = "scratch", ["class"] = "org.example.Terminal" } },
  ["workspaces"] = {
    ["1"] = { ["app"] = "browser", ["class"] = "org.example.Browser" },
    ["2"] = {
      ["split"] = "columns",
      ["ratios"] = { 0.5, 0.5 },
      ["children"] = {
        { ["split"] = "columns", ["ratios"] = { 0.5, 0.5 }, ["children"] = {
          { ["app"] = "chat-a", ["class"] = "org.example.ChatA" },
          { ["app"] = "chat-b", ["class"] = "org.example.ChatB" },
        } },
        { ["app"] = "editor", ["class"] = "org.example.Editor" },
      },
    },
  },
}
]]

-- Internal panel: the same profile, but the workspaces must fall back to the built-in scrolling
-- layout and get no cells at all.
local internal_fixture = [[
return {
  ["version"] = 1,
  ["mode"] = "internal",
  ["workspaces"] = {
    ["1"] = { ["app"] = "browser", ["class"] = "org.example.Browser" },
    ["2"] = { ["split"] = "rows", ["children"] = {
      { ["app"] = "chat-a", ["class"] = "org.example.ChatA" },
      { ["app"] = "editor", ["class"] = "org.example.Editor" },
    } },
  },
}
]]

local function write_profile(text)
  local handle = assert(io.open(state_dir .. "/profile.lua", "w"))
  handle:write(text)
  handle:close()
end

local registered, rules = nil, {}

hl = {
  layout = { register = function(_name, provider) registered = provider end },
  workspace_rule = function(spec) rules[#rules + 1] = spec end,
}

local function load_module()
  registered, rules = nil, {}
  dofile(module_path)
  assert(registered and registered.recalculate, "layout was not registered")
end

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
local function check(label, condition, detail)
  if not condition then
    fails = fails + 1
  end
  print(string.format("%-41s %s%s", label, condition and "PASS" or "FAIL", detail and ("  " .. detail) or ""))
end

local function overlaps(a, b)
  return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h
end

local function inside(box, area)
  return box.x >= area.x
    and box.y >= area.y
    and box.x + box.w <= area.x + area.w
    and box.y + box.h <= area.y + area.h
end

local function pairwise_disjoint(cells)
  for i = 1, #cells do
    for j = i + 1, #cells do
      if overlaps(cells[i], cells[j]) then
        return false, string.format("%s overlaps %s", fmt(cells[i]), fmt(cells[j]))
      end
    end
  end
  return true
end

--------------------------------------------------------------------------- external mode

write_profile(fixture)
load_module()

local classes = { "org.example.ChatA", "org.example.ChatB", "org.example.Editor" }
local nested = run(classes, 2)
local chat_a, chat_b, editor = nested[classes[1]], nested[classes[2]], nested[classes[3]]

check("every profile window is placed", chat_a and chat_b and editor)
check("cells are pairwise disjoint", pairwise_disjoint({ chat_a, chat_b, editor }))
check("cells stay inside the work area", inside(chat_a, AREA) and inside(chat_b, AREA) and inside(editor, AREA))
check("profile order is left to right", chat_a.x < chat_b.x and chat_b.x < editor.x,
  string.format("%s | %s | %s", fmt(chat_a), fmt(chat_b), fmt(editor)))
check("gap between adjacent cells is exact",
  chat_b.x - (chat_a.x + chat_a.w) == GAP and editor.x - (chat_b.x + chat_b.w) == GAP)
check("the two outer halves are equal", math.abs(editor.w - (chat_b.x + chat_b.w - chat_a.x)) <= 2,
  string.format("left block %d, right block %d", chat_b.x + chat_b.w - chat_a.x, editor.w))
check("the inner pair is equal within a pixel", math.abs(chat_a.w - chat_b.w) <= 1,
  string.format("%d vs %d", chat_a.w, chat_b.w))
check("every cell fills the workspace height", chat_a.h == AREA.h and editor.h == AREA.h)

local single = run({ "org.example.Browser" }, 1)
check("a single window fills the area",
  single["org.example.Browser"].w == AREA.w and single["org.example.Browser"].h == AREA.h,
  fmt(single["org.example.Browser"]))

local partial = run({ classes[1], classes[3] }, 2)
check("a missing app keeps its cell free",
  partial[classes[1]].x == chat_a.x and partial[classes[1]].w == chat_a.w, fmt(partial[classes[1]]))
check("a missing app does not shift the others",
  partial[classes[3]].x == editor.x and partial[classes[3]].w == editor.w, fmt(partial[classes[3]]))

local extra = run({ classes[1], classes[2], classes[3], "org.example.Other" }, 2)
local other = extra["org.example.Other"]
print("window outside the profile: " .. (fmt(other) or "NOT PLACED"))
check("a window outside the profile is placed", other ~= nil)
check("nothing overlaps the outside window", pairwise_disjoint({
  extra[classes[1]], extra[classes[2]], extra[classes[3]], other,
}))
check("the outside window takes the right side", other.x > extra[classes[3]].x,
  fmt(other) .. " vs " .. fmt(extra[classes[3]]))
check("the profile block keeps its left edge", extra[classes[1]].x == AREA.x)

check("an empty workspace is a no-op", next(run({}, 2)) == nil)

local layouts = {}
for _, rule in ipairs(rules) do
  layouts[tostring(rule.workspace)] = rule.layout
end
check("a rule is registered per profile workspace", #rules == 2, tostring(#rules))
check("ws 1 uses the custom layout", layouts["1"] == "lua:omarchy-layout", tostring(layouts["1"]))
check("ws 2 uses the custom layout", layouts["2"] == "lua:omarchy-layout", tostring(layouts["2"]))

--------------------------------------------------------------------------- internal mode

write_profile(internal_fixture)
load_module()

local internal_layouts = {}
for _, rule in ipairs(rules) do
  internal_layouts[tostring(rule.workspace)] = rule.layout
end
check("internal: ws 1 falls back to scrolling", internal_layouts["1"] == "scrolling",
  tostring(internal_layouts["1"]))
check("internal: ws 2 falls back to scrolling", internal_layouts["2"] == "scrolling",
  tostring(internal_layouts["2"]))
check("internal: no cells are placed", next(run({ "org.example.ChatA" }, 2)) == nil)

print(fails == 0 and "ALL PASS" or (fails .. " FAILURES"))
os.exit(fails == 0 and 0 or 1)
