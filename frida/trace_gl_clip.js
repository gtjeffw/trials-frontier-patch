// Log each distinct glScissor / glViewport / scissor-test toggle / stencil use with the calling game function.
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_gl_clip.js   (stay attached)
const gl = Process.getModuleByName("OpenGLES");
const seen = new Set();
const ts = () => new Date().toISOString().slice(11, 19);
function caller(ctx) {
  const frames = Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 3).map(a => {
    const s = DebugSymbol.fromAddress(a);
    return s.moduleName === "TrialsFrontier" ? (s.name || a) : null;
  }).filter(x => x);
  return frames.join(" < ");
}
function hook(name, fmt, filter) {
  const p = gl.findExportByName(name);
  if (!p) { console.log("missing " + name); return; }
  Interceptor.attach(p, {
    onEnter(a) {
      if (filter && !filter(a)) return;
      const line = `${name}(${fmt(a)}) <- ${caller(this.context)}`;
      if (!seen.has(line)) { seen.add(line); console.log(`${ts()} ${line}`); }
    }
  });
}
const i4 = a => [0, 1, 2, 3].map(i => a[i].toInt32()).join(",");
hook("glScissor", i4);
hook("glViewport", i4);
const CAPS = { 0xc11: "SCISSOR_TEST", 0xb90: "STENCIL_TEST" };
hook("glEnable", a => CAPS[a[0].toUInt32()], a => a[0].toUInt32() in CAPS);
hook("glDisable", a => CAPS[a[0].toUInt32()], a => a[0].toUInt32() in CAPS);
hook("glStencilFunc", a => `0x${a[0].toUInt32().toString(16)},${a[1].toInt32()},0x${a[2].toUInt32().toString(16)}`);
console.log("clip tracer attached");
