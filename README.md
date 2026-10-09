# omarchy-layout

Start and place your base windows at login on an Omarchy desktop (Hyprland 0.56, Lua config).

Windows stay tiled, never floated. The profile describes a tree per workspace: a leaf names an app,
`columns`/`rows` nodes split the work area. Hyprland hands each profiled workspace to a custom Lua
layout, which places every window in the cell the tree gives it. On the internal laptop panel (no
external output enabled) the profile switches those workspaces to Hyprland's built-in `scrolling`
layout with full-size windows instead of pixel cells.

## Parts

| Path | What it is |
| :--- | :--- |
| `bin/layout` | the `omarchy-layout` CLI and the engine: profile compilation, launching, placement, checks |
| `hypr/omarchy-layout.lua` | the Hyprland custom layout, registered as `lua:omarchy-layout` |
| `manifest.json`, `Service.qml` | a Quickshell service plugin that runs `omarchy-layout apply` once per shell start (repo root, so the repo is itself an installable plugin) |
| `profiles/example.json` | neutral template; your own profile is `profiles/windows.json` (git-ignored) |
| `tests/layout_spec.lua` | hermetic test of the placement rules, no session required |

Requirements: Hyprland 0.55+ with the Lua config parser, Omarchy 4.x, Python 3.9+ (stdlib only).
`lua5.4` is needed only to run the test.

## Install

Two routes; both end with the same three artefacts in place.

**From the shell's plugin manager** (clones the repo and enables it):

```sh
omarchy plugin add https://github.com/ivanvan08/omarchy-layout --enable --yes
```

**From a local checkout** (`./install.sh`), which symlinks instead of cloning:

| Link | Points at |
| :--- | :--- |
| `~/.config/omarchy/plugins/io.github.ivanvan08.layout` | the repo |
| `~/.local/bin/omarchy-layout` | `bin/layout` |
| `~/.config/hypr/omarchy-layout.lua` | `hypr/omarchy-layout.lua` |

It also rescans the shell plugin list and runs `omarchy plugin enable io.github.ivanvan08.layout`.

Then add one line to `~/.config/hypr/hyprland.lua`, next to the other `require`s:

```lua
dofile((os.getenv("HOME") or "") .. "/.config/hypr/omarchy-layout.lua")
```

`dofile` rather than `require` for two reasons: Omarchy's `bootstrap.lua` maps a dotted module name
to a path (`require("hypr.x")` would look for `~/.config/hypr/hypr/x.lua`), and it prunes only the
`default.hypr`, `hypr` and `omarchy.current.theme` prefixes from `package.loaded` on a reload, so a
`require`d module would stay cached and never re-register the layout after `hyprctl reload`.

Reload the compositor config once (`hyprctl reload`) and check that nothing else broke:

```sh
hyprctl configerrors     # must print nothing
```

## Enable is not optional

The shell mounts a third-party `service` plugin only when its id is listed in the `plugins[]` array
of `~/.config/omarchy/shell.json`. `omarchy-shell shell rescanPlugins` only rescans; it does not
enable. Verify with:

```sh
omarchy plugin list --json | jq '.[] | select(.id == "io.github.ivanvan08.layout")'
```

If the service fails to load, the shell says why:

```sh
journalctl --user --since "10 minutes ago" | grep "service plugin load failed"
```

## Profile

`profiles/windows.json` is the hand-edited source of truth and is git-ignored, so a personal app set
never lands in a public repository. Copy the template to start:

```sh
cp profiles/example.json profiles/windows.json
```

Schema:

```json
{
  "version": 1,
  "scratchpad": [
    { "app": "scratch", "class": "org.example.Terminal", "exec": "my-terminal --attach" }
  ],
  "workspaces": {
    "1": { "app": "browser", "class": "org.example.Browser", "exec": "example-browser" },
    "2": {
      "split": "columns",
      "ratios": [0.5, 0.5],
      "children": [
        {
          "split": "columns",
          "ratios": [0.5, 0.5],
          "children": [
            { "app": "chat-a", "class": "org.example.ChatA", "exec": "chat-a" },
            { "app": "chat-b", "class": "org.example.ChatB", "exec": "chat-b" }
          ]
        },
        { "app": "editor", "class": "org.example.Editor", "exec": "editor" }
      ]
    },
    "3": {
      "layout": "center",
      "split": "columns",
      "children": [
        { "app": "notes", "class": "org.example.Notes", "exec": "notes" },
        { "app": "terminal", "class": "org.example.Terminal", "exec": "terminal" },
        { "app": "preview", "class": "org.example.Preview", "exec": "preview" }
      ]
    }
  }
}
```

- **Leaf**: `app` (label for reporting), `class` (the value Hyprland reports for the window, see
  `hyprctl clients -j`), `exec` (shell command to start it), optional `"launch_first": true` (started
  before the other apps, for a slow starter such as Discord with its updater).
- **Internal node**: `split` (`"columns"` or `"rows"`), optional `ratios` (each share of the
  remaining space, equal when omitted), `children` in left-to-right / top-to-bottom order.
- **Top level**: `version`, optional `scratchpad` (list of leaves launched into the scratchpad and
  revealed by the usual `SUPER + S`), `workspaces` (one tree per workspace number).
- **Centre preset**: `"layout": "center"`, `"split": "columns"`, and exactly three leaves in
  `"children"` (`[left, middle, right]`). Optional `"ratios": [s, c, s]` with equal side shares `s`;
  the centre ratio `c` defaults to 0.5.

Placement rules:

- Leaves are matched to live windows by `class`, in tree order.
- A leaf whose app is not running keeps its cell **reserved**: the other windows stay where the
  profile puts them instead of stretching over the gap.
- Windows that are not in the tree fill free cells first, then the right half of the work area, so an
  extra window never overlaps a profiled one.
- Ratios, not pixels: the compositor computes the pixel geometry from the work area, so the same
  profile works on a different monitor or scaling.
- `scratchpad` entries are tracked by the address of the window this tool launched (state file
  `scratchpad.json`), not by class, because a terminal-running app shares its class with every other
  terminal of the same emulator. Give an entry a class of its own and `"rule": true` (for herdr:
  `uwsm-app -- ghostty --class=org.omarchy.herdr -e herdr`) and a window rule sends it to the scratchpad
  before it is ever shown; an `org.omarchy.*` class keeps Omarchy's `terminal` tag
  (`default/hypr/apps/terminals.lua`).
- Every regular leaf also gets a **window rule** at config load:
  `hl.window_rule({ match = { class = "^<class>$" }, workspace = "<N> silent" })`. The compositor then
  puts the window on its workspace the moment it maps, however late that is, and without moving
  focus. This is what catches apps that map a splash or updater window first and their real window
  much later (Discord): launch-and-move from the CLI would only ever catch the first window. The
  side effect is that **any** new window of that class opens on that workspace; a leaf opts out with
  `"rule": false`. Scratchpad entries get a rule only with `"rule": true`. Rules are registered when the
  config loads, so a profile edit takes effect after `hyprctl reload`. Rules that send a window somewhere
  hidden (the park below, the scratchpad) also set `no_initial_focus` and `focus_on_activate = false`: an
  app Hyprland launched gets an activation token, and a GTK app (ghostty) uses it on start, which showed
  the scratchpad and focused the window despite `silent`.

## CLI

```
omarchy-layout apply                # idempotent: launch what is missing, place everything
omarchy-layout apply --dry-run      # print the plan, change nothing
omarchy-layout apply --verbose      # log launches, placements and the geometry table
omarchy-layout apply --timeout 90   # seconds to wait per window (default 45)
omarchy-layout apply --watch 0      # disable the late-arrival watch (see below)
omarchy-layout plan                 # the same plan, read-only
omarchy-layout status               # each profile window: running or not, on which workspace
omarchy-layout status --compare     # adds expected vs actual rects and the worst delta
omarchy-layout save [workspace]     # overwrite that workspace's node from the live session
omarchy-layout list                 # one line per workspace
omarchy-layout order [workspace]    # bring built-in-layout workspaces to their profile tree
omarchy-layout order --check        # report only, move nothing
```

`apply` does five things, and only the first one launches anything:

1. launches every profile window that is not running, targeting a workspace the window does not
   choose by itself: it waits for the window's `openwindow` event on the Hyprland socket and moves it,
2. re-places profile windows that are already running on the wrong workspace,
3. keeps watching the event stream until it has been quiet for `--watch` seconds (at most
   `--watch-cap`) and places **late arrivals**: some apps, Electron ones especially, map a splash
   window first and remap the real one afterwards, and a remap is a fresh event on whatever workspace
   is current at that moment. Without this phase such a window stays wherever it happened to open,
4. keeps **built-in-layout workspaces in their profile tree** (see below) after every arrival or
   departure during that watch,
5. compiles the profile and re-asserts the workspace rules, then reports the geometry diff.

A lock file (`~/.local/state/omarchy/layout/apply.lock`) makes concurrent runs impossible: `apply` is
started both by the compositor's autostart and by the shell service, and two runs could otherwise
double-launch an app. A second run prints `another apply is already running` and exits 0.

It exits non-zero when a window did not appear or could not be moved, so a wrapper or the service log
can tell a clean run from a partial one.

`save` reads the tiled windows of a workspace (the focused one by default), sorts them, writes them
back as that workspace's tree with ratios derived from the live geometry, and always writes
`profiles/windows.json`. It is the fastest way to grow a profile from a session that already looks
right.

Environment overrides:

| Variable | Effect |
| :--- | :--- |
| `OMARCHY_LAYOUT_PROFILE` | profile file to read (default: `profiles/windows.json`, else `profiles/example.json`) |
| `OMARCHY_LAYOUT_STATE` | state directory (default `~/.local/state/omarchy/layout`) |
| `OMARCHY_LAYOUT_FAKE_MONITORS` | comma-separated monitor names, to test the internal-panel branch without unplugging anything |
| `OMARCHY_LAYOUT_LAUNCH_TIMEOUT` | default for `--timeout` |
| `OMARCHY_LAYOUT_WATCH` | default for `--watch` (seconds of quiet before the late-arrival watch stops) |
| `OMARCHY_LAYOUT_WATCH_CAP` | default for `--watch-cap` (hard limit for that watch) |
| `OMARCHY_LAYOUT_PARK_CAP` | how long a parked workspace waits for its slowest window, seconds (default 300) |

State lives in `~/.local/state/omarchy/layout/`: `profile.lua` (compiled from the profile JSON),
`scratchpad.json`, `assembled-<session>-<workspace>` (see "Assembly out of sight"), `last-apply` (ISO
timestamp written by every run, including the automatic one) and `log` (one line per run).

## How it is wired to Hyprland

The Lua module registers the layout and attaches it to the profiled workspaces:

```lua
hl.layout.register("omarchy-layout", { recalculate = function(ctx) ... end })
hl.workspace_rule({ workspace = N, layout = "lua:omarchy-layout" })
```

`recalculate` receives `ctx.area` (the work area) and `ctx.targets` (the workspace's tiled windows) and
calls `target:place(ctx:split(box, side, ratio))` per window: Hyprland subtracts gaps and reserved
space itself, so the module only deals in boxes.

`apply` also writes the rule into `~/.local/state/omarchy/workspace-layouts/<workspace>.lua`, the file
Omarchy loads on every config load. Both mechanisms are kept in sync because a rule registered at
runtime does not move a workspace that already exists: the layout of a workspace is fixed when the
workspace is created. Files left there by an older tool otherwise win and hand the workspace `dwindle`
or `scrolling`. Layout files are persisted only when running the default profile; with
`OMARCHY_LAYOUT_PROFILE` set, rules apply at runtime only so temporary probe runs leave no files behind.
When persisting, `apply` removes stale layout files carrying its header for workspaces no longer in the
profile, while leaving unrelated files (such as Omarchy's layout toggles) untouched.

## Startup

There are two launch points, and both are wanted:

- **The compositor's own autostart**, which is the fast path. Add to `~/.config/hypr/autostart.lua`:

  ```lua
  o.launch_on_start("bash -c 'sleep 1 && ~/.local/bin/omarchy-layout apply --quiet'")
  ```

  This runs as soon as the Hyprland config is loaded, before the shell exists, so the windows come up
  as early as the session allows. `apply` is idempotent and locked, so the second launch point costs
  nothing.
- **The shell service** (`Service.qml`), which is the safety net: it waits for the first Hyprland raw
  event (or 1 s, whichever comes first) and runs `omarchy-layout apply` once per shell start. It picks
  up whatever the autostart missed, including windows that arrived late.

The root type of `Service.qml` is `Item`, not `Service`: a file named `Service.qml` whose root is
`Service` inherits from itself and the shell refuses it with `Service is instantiated recursively`.
First-party services are plain `Item`s too (`plugins/services/battery/Service.qml`).

## Troubleshooting

- **A window sits on the wrong workspace right after login.** Check that its leaf has no
  `"rule": false` and that the class in the profile is exactly what `hyprctl clients -j` reports: the
  window rule matches the class exactly. After editing the profile, `hyprctl reload` re-registers the
  rules. The late-arrival watch is the second line of defence; the log says when it fired:

  ```sh
  grep "late arrival placed" ~/.local/state/omarchy/layout/log
  ```
- **Something launched twice at login.** Two applies can both look for a missing window; the lock file
  exists to prevent that. If you see it, check that only one `apply` is in flight and that
  `~/.local/state/omarchy/layout/apply.lock` is not stale (it is ignored after 5 minutes).
- **Nothing happens at login.** Check the three links exist, that `hyprctl configerrors` is empty, that
  the plugin id is in `shell.json` `plugins[]`, and that `omarchy-layout apply` works when run by hand.
- **`hyprctl dispatch <name>` does not work.** Under the Lua parser the argument is wrapped as
  `hl.dispatch(<argument>)`, so a legacy dispatcher name is a syntax error and Hyprland shows an error
  overlay. Pass an `hl.dsp.*` expression instead:

  ```sh
  hyprctl dispatch 'hl.dsp.window.move({ window = "address:0x...", workspace = "2", follow = false })'
  hyprctl eval 'hl.dispatch(hl.dsp.window.move({ window = "address:0x...", workspace = "2" }))'  # equivalent
  ```

- **A dispatched call returns `ok` but nothing happened.** Both forms above report `ok` even when the
  call was a no-op. Verify the result (`hyprctl clients -j`) instead of trusting the reply.
- **Window addresses differ between tools.** `.socket2.sock` prints them without the `0x` prefix,
  `hyprctl clients -j` prints them with it. Compare normalised addresses.
- **`hyprctl keyword` is a silent no-op** under the Lua parser: it returns success and changes
  nothing.
- **A workspace keeps its old layout.** Rules apply when the workspace is created; move its windows out
  and back, or reload the config, to have it pick up the rule. The layout name a workspace reports
  can lag behind the layout actually computing the geometry, so compare rects
  (`omarchy-layout status --compare`), not names.
- **Check state by hand:**

  ```sh
  hyprctl workspaces -j | jq -r '.[] | "\(.id) \(.tiledLayout)"'
  hyprctl clients -j | jq -r '.[] | "\(.workspace.id) \(.class) \(.at) \(.size)"'
  omarchy-layout status --compare
  jq -R . ~/.local/state/omarchy/layout/last-apply
  ```

## Optional: launcher menu entry

To re-apply the layout from the Omarchy menu, add this to
`~/.config/omarchy/extensions/omarchy-menu.jsonc` (it hot-reloads on save):

```jsonc
  "layout": { "label": "Window layout" },
  "layout.apply": {
    "label": "Re-apply base windows",
    "action": "omarchy-layout apply",
    "description": "Start and place the profile's base windows"
  },
```

The parent is inferred from the dotted id, so `layout` becomes a root entry and `layout.apply` its
child.

## Manual resizing

Hyprland has no resize hook for a custom layout: `resizeactive` (the `SUPER + arrow` bindings and the
mouse drag) is implemented per built-in layout, a Lua provider is never asked, and no `layout_msg`
arrives for it. Measured on Hyprland 0.56.2: the same `hl.dsp.window.resize({ relative = true })` that
changes a tiled window's width under `dwindle` does nothing while the workspace runs
`lua:omarchy-layout`.

So a managed workspace is a fixed arrangement: exact cells, no manual resizing. A workspace where
resizing matters is better off under a built-in layout, and the profile can say so per workspace:

```json
"2": { "layout": "dwindle", "split": "columns", "children": [ ... ] }
```

Such a workspace is still launched and targeted by `apply` (the windows go to the workspace, in profile
order), but its geometry belongs to `dwindle` and the layout provider keeps its hands off it. Any
built-in layout name works, `scrolling` included.

### Tree shape on a built-in-layout workspace

A built-in layout decides by itself where a new window goes. On dwindle with Hyprland's defaults
(`dwindle:use_active_for_splits = true`) a window that lands on a workspace with no focused window
splits the window **nearest the cursor**, and `dwindle:force_split` decides which side it takes
(`DwindleAlgorithm.cpp`, Hyprland 0.56.2). When the apps of one workspace arrive at different times,
which is normal at login, the tree is decided by wherever the mouse happened to be.

The tree matters, not only the order: `[[a | b] | c]` and `[a | [b | c]]` both read a, b, c left to
right, but in the first `c` spans a half and in the second `a` does. So `apply` compares **cell
geometry**: it computes the cells dwindle makes for the profile tree (every split at one half, n
children nesting to the right) on the live work area and checks which window sits in which cell,
within 32 px.

- Right cells, wrong windows: they are swapped with `hl.dsp.window.swap({ window, target })`.
- Wrong tree: it is rebuilt. Every window but the first is parked on a hidden special workspace
  (`special:omarchy-layout-park`) and moved back one by one in build order. Before each move the window
  to split is made dwindle's target: the cursor is put inside it when it is not there already, and when
  you have focus on that workspace, focus goes to it (dwindle splits the focused window then). Cursor and
  focus are put back, and a parked window is always returned, even when a step fails.

Building needs `dwindle:use_active_for_splits = true` (otherwise dwindle ignores cursor and focus),
`force_split` 0 or 2 (1 puts every new window first) and a profile whose splits match the cell shapes
(dwindle splits a wide cell side by side, so `rows` in a wide cell cannot be built). Otherwise it reports
`unsupported` and moves nothing.

Only a workspace the run is assembling is touched: one whose window this run launched, or one a window
arrived on or left during the watch. A plain `apply` on a settled desktop does not undo your resizing.
When the run launched one of the workspace's windows itself, the watch holds for the whole
`--watch-cap`, because an app with an updater window (Discord) maps its real window long after the
updater went quiet. A workspace with a window outside the profile is left as you arranged it.

### Centre preset (master layout)

A workspace node with `"layout": "center"` runs Hyprland's built-in `master` layout with
`orientation = "center"`. It places three windows:

- The middle window takes the centre of the screen at full height with width governed by `mfact`
  (default 0.5 of the work area).
- The other two windows are equal columns flanking it on the left and right.
- Windows remain ordinary tiled windows: dragging with `SUPER + LMB` moves and swaps windows
  natively using master's drop logic, and border/keyboard resize (`resizeactive`) works natively.

**Scope of `mfact`**: In Hyprland 0.56.2 `mfact` is global (`master:mfact`); workspace rule
`layout_opts` only parses `orientation`, not `mfact`. Therefore, the module sets global
`master:mfact` from the preset's centre ratio whenever the profile contains a centre preset, and
every workspace running the master layout shares that ratio.

**Assembly out of sight**: Like `dwindle`, a centre preset workspace is assembled out of sight: its
windows wait in `special:omarchy-layout-park` at login. Once all three windows have mapped, `apply`
moves them into the workspace in any order, then fixes window positions with swaps (`plan_swaps` and
`hl.dsp.window.swap({ window, target })`). No cursor or focus moves are made. A settled workspace that
`apply` is not assembling is never touched, so user resizing survives subsequent runs.

### Assembly out of sight

At login a built-in-layout workspace is not built where you can see it. Until `apply` has assembled it
in this Hyprland session, the window rules of its apps send them to the hidden
`special:omarchy-layout-park` (silently, without focus), and the rules to the workspace itself are
registered disabled. Once every leaf has its window there, `apply` moves them in in build order, so
dwindle builds the profile tree; the screen stays on whatever workspace you are on, and an updater or
splash window (Discord's floats: fixed size, no frame) never takes a tile. Then it switches the rules
over through `hyprctl eval` (it shares the config's Lua state; the rule objects are in the global
`omarchy_layout_rules`) and writes `assembled-<HYPRLAND_INSTANCE_SIGNATURE>-<workspace>`, so a config
reload in the same session keeps the normal rules and later windows of those apps open on the workspace
as usual. A slow app does not hold the workspace hidden forever: after `OMARCHY_LAYOUT_PARK_CAP` seconds
(default 300) whatever has arrived is moved in, and a run that ends for any reason moves parked windows
in before it exits. `omarchy-layout order` does the same at once.

`omarchy-layout order` runs the same check once, on demand, and prints `ok`, `swapped`, `rebuilt`,
`assembled`, `flushed`, `incomplete`, `foreign`, `unsupported` or `failed` per workspace. It never
launches anything, and a rebuild resets that workspace's split ratios to halves.
`omarchy-layout order --check` only reports (`ok`, `swap`, `rebuild`, `incomplete`, `foreign`) and
exits 1 when something would change.

The layout does learn from a manual geometry change when the host delivers one (`target.box` differing
from the box the layout placed is turned into a new split ratio, and a single-window workspace keeps
the box it was given), which is what makes the provider behave if a future Hyprland build does route
resizing to custom layouts.

## Diagnostics

Lua `print` from the config state does not reach the compositor log, so the layout writes to
`/tmp/omarchy-layout-debug.log` **only while that file exists**:

```sh
touch /tmp/omarchy-layout-debug.log     # turn diagnostics on
rm /tmp/omarchy-layout-debug.log        # turn them off
```

Each line records a recalculation: the work area, the window set, every cell the layout computed,
every ratio it learned, and any layout message the compositor sent.

## Tests

The placement rules are checked hermetically: no session, no compositor, no live state, synthetic app
names and an arbitrary work area.

```sh
OMARCHY_LAYOUT_STATE=$(mktemp -d) lua5.4 tests/layout_spec.lua
```

The test writes a fixture profile into that scratch directory, fakes `ctx.area`, `ctx.targets`,
`ctx:split` and `target:place`, and asserts: every profile window is placed, cells are pairwise
disjoint and inside the work area, the gaps between adjacent cells are exact, a missing app keeps its
cell without shifting the others, a window outside the profile is placed to the right of the profile
block without overlapping, an empty workspace is a no-op, a rule is registered per profile workspace,
and in internal mode the workspaces fall back to `scrolling` with no cells placed.

The comparison of a built-in-layout workspace with its profile tree has its own hermetic test: the
wrong-tree geometry measured live (it reads in profile order and still needs a rebuild), the right tree,
right cells with wrong windows, a missing and an extra window, the insertion plan and its simulated
cells, which split shapes dwindle can build, and the swap planning over every permutation of four.

```sh
python3 -m unittest tests/test_order.py
```

## Uninstall

```sh
./install.sh --uninstall          # removes the three symlinks and disables the plugin
```

Then remove the `dofile(... omarchy-layout.lua)` line from `~/.config/hypr/hyprland.lua` and run
`omarchy-shell shell rescanPlugins`. If you installed through `omarchy plugin add`, use
`omarchy plugin disable io.github.ivanvan08.layout` followed by `omarchy plugin remove`.

## License

MIT.
