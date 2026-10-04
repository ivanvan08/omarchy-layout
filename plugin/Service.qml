import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

// Runs `omarchy-layout apply` exactly once per shell start. The CLI itself is
// idempotent, but the shell start path is not: the first Hyprland raw event and
// the fallback timer can both fire, so a guard keeps this to a single call.
Service {
  id: root

  // Hyprland is up (first raw event seen, or the fallback timer elapsed).
  property bool ready: false
  // `omarchy-layout` was found in PATH.
  property bool hasBinary: false
  // An apply has been launched (or a missing binary was reported).
  property bool applied: false

  function tryApply() {
    if (applied || !ready || !hasBinary) return
    applied = true
    applyProc.running = true
  }

  // Availability probe: a direct Process to a missing binary does not always
  // surface an exit code, so resolve it through the shell first.
  Process {
    id: checkProc
    command: ["sh", "-c", "command -v omarchy-layout"]
    running: true
    onExited: (code) => {
      if (code !== 0) {
        console.warn("omarchy-layout: 'omarchy-layout' not found in PATH; layout service stays idle")
        return
      }
      root.hasBinary = true
      root.tryApply()
    }
  }

  Process {
    id: applyProc
    command: ["omarchy-layout", "apply"]
    onExited: (code) => {
      if (code !== 0)
        console.warn("omarchy-layout: apply exited with code " + code)
    }
  }

  // Readiness: the first raw Hyprland event means the compositor is serving IPC.
  Connections {
    target: Hyprland
    function onRawEvent(event) {
      root.ready = true
      root.tryApply()
    }
  }

  // Fallback in case no event ever arrives (quiet desktop at startup).
  Timer {
    interval: 5000
    repeat: false
    running: true
    onTriggered: {
      root.ready = true
      root.tryApply()
    }
  }
}
