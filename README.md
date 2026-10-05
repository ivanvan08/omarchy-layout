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
    }
  }
}
```

- **Leaf**: `app` (label for reporting), `class` (the value Hyprland reports for the window, see
  `hyprctl clients -j`), `exec` (shell command to start it).
- **Internal node**: `split` (`"columns"` or `"rows"`), optional `ratios` (each share of the
  remaining space, equal when omitted), `children` in left-to-right / top-to-bottom order.
- **Top level**: `version`, optional `scratchpad` (list of leaves launched into the scratchpad and
  revealed by the usual `SUPER + S`), `workspaces` (one tree per workspace number).

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
  terminal of the same emulator.

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
```

`apply` does four things, and only the first one launches anything:

1. launches every profile window that is not running, targeting a workspace the window does not
   choose by itself: it waits for the window's `openwindow` event on the Hyprland socket and moves it,
2. re-places profile windows that are already running on the wrong workspace,
3. keeps watching the event stream until it has been quiet for `--watch` seconds (at most
   `--watch-cap`) and places **late arrivals**: some apps, Electron ones especially, map a splash
   window first and remap the real one afterwards, and a remap is a fresh event on whatever workspace
   is current at that moment. Without this phase such a window stays wherever it happened to open,
4. compiles the profile and re-asserts the workspace rules, then reports the geometry diff.

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

State lives in `~/.local/state/omarchy/layout/`: `profile.lua` (compiled from the profile JSON),
`scratchpad.json`, `last-apply` (ISO timestamp written by every run, including the automatic one) and
`log` (one line per run).

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
or `scrolling`.

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

- **A window sits on the wrong workspace right after login.** Apps that remap their window after
  starting (Electron ones especially) land on whatever workspace is current at that moment. The
  late-arrival watch is what fixes it; the log says when it fired:

  ```sh
  grep "late arrival placed" ~/.local/state/omarchy/layout/log
  ```

  Raise `--watch` if an app remaps later than the watch window.
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

## Uninstall

```sh
./install.sh --uninstall          # removes the three symlinks and disables the plugin
```

Then remove the `dofile(... omarchy-layout.lua)` line from `~/.config/hypr/hyprland.lua` and run
`omarchy-shell shell rescanPlugins`. If you installed through `omarchy plugin add`, use
`omarchy plugin disable io.github.ivanvan08.layout` followed by `omarchy plugin remove`.

## License

MIT.
