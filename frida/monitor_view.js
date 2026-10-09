// Long-lived monitor: every 2 s (on the main queue) log view/layer/screen geometry and the engine's render/touch
// globals, printing only when something changes. Also logs each distinct glViewport size.
// Usage: frida -p <pid> -q -t 3600 -l frida/monitor_view.js
// Stay attached for the whole session: detaching has left the process crash-prone (stale unwind state).
// Avoid ObjC.choose / heap scans and ObjC.Object on PlayTools touch objects: both hung or crashed the game.
const base = Process.mainModule.base.sub(0x100000000);
const rd = a => base.add(a).readS32();
const rect = r => `${r[0][0]},${r[0][1]} ${r[1][0]}x${r[1][1]}`;
let last = "";

function snapshot() {
  const app = ObjC.classes.UIApplication.sharedApplication();
  const win = app.keyWindow() || app.windows().firstObject();
  if (!win) return "no window";
  const vc = win.rootViewController();
  const v = vc ? vc.view() : null;
  const s = win.screen();
  const parts = [`window=${rect(win.frame())}`, `screen=${rect(s.bounds())}@${s.scale()} native=${rect(s.nativeBounds())}`];
  if (v) {
    const l = v.layer();
    parts.push(`view(${v.$className})=${rect(v.frame())} csf=${v.contentScaleFactor()}`);
    parts.push(`layer=${rect(l.bounds())} pos=${l.position()} cs=${l.contentsScale()}`);
  }
  parts.push(`render=${rd(0x100f2ada0)}x${rd(0x100f2ada4)} touch=${rd(0x100f2adb4)}x${rd(0x100f2adb8)}*${rd(0x100f2adbc)}`);
  return parts.join(" | ");
}

setInterval(() => {
  ObjC.schedule(ObjC.mainQueue, () => {
    try {
      const s = snapshot();
      if (s !== last) { console.log(new Date().toISOString().slice(11, 19) + " " + s); last = s; }
    } catch (e) { console.log("snapshot error: " + e); }
  });
}, 2000);

const seen = new Set();
Interceptor.attach(Process.getModuleByName("OpenGLES").findExportByName("glViewport"), {
  onEnter(a) {
    const k = [0, 1, 2, 3].map(i => a[i].toInt32()).join(",");
    if (!seen.has(k)) { seen.add(k); console.log(new Date().toISOString().slice(11, 19) + ` glViewport(${k})`); }
  }
});
console.log("monitor attached");
