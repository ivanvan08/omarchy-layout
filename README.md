# omarchy-layout

Applies a saved window layout on an Omarchy (Hyprland 0.56, Lua config) desktop.

Windows are tiled, never floated. The layout places each window into a cell
defined by the profile: a leaf cell names an app, the tree of `split` /
`children` nodes defines the columns and rows. On the internal laptop panel a
scrolling layout with full-size windows is used instead, so windows keep a
usable size on a small screen.

Three parts:

- `bin/layout` - the `omarchy-layout` CLI and layout engine.
- `hypr/omarchy-layout.lua` - the Hyprland custom layout, registered as
  `lua:omarchy-layout` and attached to workspaces via workspace rules.
- `manifest.json` + `Service.qml` - a Quickshell service plugin that runs
  `omarchy-layout apply` once at shell startup. They sit at the repo root so the
  repo is itself a valid plugin and `omarchy plugin add` can install it.

## Install

The plugin part is installed by the shell's own command, which clones the repo
into `~/.config/omarchy/plugins/<id>/` and enables it:

```sh
omarchy plugin add https://github.com/ivanvan08/omarchy-layout --enable --yes
```

From a local checkout, `./install.sh` does the same by symlinking: the repo is
linked as `~/.config/omarchy/plugins/io.github.ivanvan08.layout`, `bin/layout`
becomes `~/.local/bin/omarchy-layout`, `hypr/omarchy-layout.lua` becomes
`~/.config/hypr/omarchy-layout.lua`, and the plugin is rescanned and enabled.

Either way it does not edit `~/.config/hypr/hyprland.lua`. Add this line
yourself:

```lua
dofile((os.getenv("HOME") or "") .. "/.config/hypr/omarchy-layout.lua")
```

`dofile` rather than `require`: Omarchy's `bootstrap.lua` prunes only the
`default.hypr`, `hypr` and `omarchy.current.theme` module prefixes from
`package.loaded` on a reload, so a `require`d module would be cached and would
not re-register the layout after `hyprctl reload`. `dofile` re-runs the file
every time, which is what keeps `lua:omarchy-layout` alive across reloads.

**The plugin must be enabled or nothing runs at startup.** The shell mounts a
third-party `service` only when its id is in the `plugins[]` array of
`~/.config/omarchy/shell.json`; `omarchy-shell shell rescanPlugins` only rescans.
`omarchy plugin enable io.github.ivanvan08.layout` writes that entry, and
`omarchy plugin list --json` shows whether it took.

## Profile format

`profiles/windows.json` is the hand-edited source of truth. It is a tree per
workspace:

```json
{
  "version": 1,
  "scratchpad": [
    { "app": "herdr", "class": "com.mitchellh.ghostty", "exec": "omarchy-launch-terminal herdr" }
  ],
  "workspaces": {
    "1": { "app": "brave", "class": "brave-origin", "exec": "brave-origin" },
    "2": {
      "split": "columns",
      "ratios": [0.5, 0.5],
      "children": [
        {
          "split": "columns",
          "ratios": [0.5, 0.5],
          "children": [
            { "app": "signal", "class": "signal", "exec": "signal-desktop" },
            { "app": "telegram", "class": "org.telegram.desktop", "exec": "Telegram" }
          ]
        },
        { "app": "discord", "class": "discord", "exec": "discord" }
      ]
    }
  }
}
```

- Leaf: `app`, `class` (the value Hyprland reports for the window), `exec`.
- Internal node: `split` (`"columns"` or `"rows"`), optional `ratios` (equal
  shares when absent), and `children`.
- Top level: `version`, optional `scratchpad` (list of leaves), `workspaces`.
- Leaves are matched to live windows by `class`, in tree order; a leaf whose app
  is not running keeps its cell empty. Windows that are not in the tree fill the
  free cells, and once no cell is free the profile tree keeps the left half of
  the work area.
- `scratchpad` entries are tracked by the address of the window this tool
  launched (`~/.local/state/omarchy/layout/scratchpad.json`), because herdr runs
  inside ghostty and every terminal shares that class.

## CLI

```
omarchy-layout apply                     # idempotent: launch missing windows, apply the layout
omarchy-layout apply --dry-run           # print the plan and change nothing
omarchy-layout plan                      # the same plan, read-only
omarchy-layout status [--compare]        # profile vs live windows; --compare adds a rect diff
omarchy-layout save [workspace]          # overwrite that workspace's node from the live session
omarchy-layout list                      # one line per workspace
```

`save` reads the tiled windows of the given workspace (or the focused one),
sorts them and writes them back as the workspace's tree with ratios derived from
the live geometry - the fastest way to grow the profile from a session that
already looks right.

State lives in `~/.local/state/omarchy/layout/`: `profile.lua` (compiled from
`profiles/windows.json`), `scratchpad.json`, a `last-apply` marker with an ISO
timestamp written by every `apply`, and `log`.

## How it is wired to Hyprland

The layout is registered once with `hl.layout.register(...)` under the name
`lua:omarchy-layout`, then attached per workspace:

```lua
hl.workspace_rule({ workspace = N, layout = "lua:omarchy-layout" })
```

Each workspace listed in the profile gets this rule, so Hyprland hands that
workspace's tiling to the Lua layout.

## Troubleshooting

- Hyprland 0.55+ with the Lua config parser is required. The old
  `hyprland.conf` keyword parser is not supported.
- `hyprctl dispatch <name>` no longer works under the Lua parser: the argument
  is wrapped as `hl.dispatch(<argument>)`, so a legacy dispatcher name is a Lua
  syntax error and Hyprland shows an error overlay. The argument must be an
  `hl.dsp.*` expression, as in Omarchy's own scripts:

  ```sh
  hyprctl dispatch 'hl.dsp.window.move({ window = "address:0x...", workspace = "2", follow = false })'
  # equivalent, explicit form:
  hyprctl eval 'hl.dispatch(hl.dsp.window.move({ window = "address:0x...", workspace = "2" }))'
  ```

  Both return `ok` even when nothing happened, so a caller has to verify the
  result (`hyprctl clients -j`) instead of trusting the reply. A move dispatched
  immediately after the `openwindow` event is dropped: wait for the window to be
  mapped first.
- `hyprctl keyword` is a silent no-op under the Lua parser: it returns success
  but changes nothing. Use `hyprctl eval` instead.
- A workspace rule set with `hl.workspace_rule` while the compositor is running
  does not always re-layout a workspace that already exists; the rule is
  authoritative at config load, and `omarchy-layout apply` re-asserts it. The
  layout name a workspace reports may lag behind the layout actually computing
  the geometry - compare rects (`omarchy-layout status --compare`), not names.
- Check state with:
  - `hyprctl activeworkspace -j`
  - `hyprctl clients -j`
  - `~/.local/state/omarchy/layout/last-apply` (timestamp of the last apply)
- The startup service logs to the shell console if `omarchy-layout` is not in
  `PATH`, or if `apply` exits non-zero.

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

The parent is inferred from the dotted id, so `layout` becomes a root entry and
`layout.apply` its child. The entry is optional - `omarchy-layout apply` works
from any terminal or keybinding.

## Tests

The cell arithmetic is checked hermetically - no session, no compositor, no live state:

```sh
OMARCHY_LAYOUT_STATE=$(mktemp -d) lua5.4 tests/layout_spec.lua
```

The test writes a fixture profile into that scratch directory, fakes `ctx.area`, `ctx.targets`,
`ctx:split` and `target:place`, and asserts the cells for a nested workspace, a single-window
workspace, a window outside the profile, an app that is not running, and the workspace rules the
module registers.

## Uninstall

```sh
./install.sh --uninstall
```

This removes the three symlinks. Then remove the `dofile(... omarchy-layout.lua)`
line from `~/.config/hypr/hyprland.lua` and run
`omarchy-shell shell rescanPlugins`.

## License

MIT.
