// Log each distinct glViewport / glScissor / scissor-test toggle together with the calling game function.
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_gl_viewport.js   (stay attached; detaching has caused later crashes)
const seen = new Set();
function caller(ctx) {
  const s = DebugSymbol.fromAddress(ctx.returnAddress);
  return `${s.moduleName}!${s.name || ctx.returnAddress}`;
}
function hook(name, fmt) {
  const p = Process.getModuleByName("OpenGLES").findExportByName(name);
  if (!p) { console.log("missing " + name); return; }
  Interceptor.attach(p, {
    onEnter(args) {
      const line = `${name}(${fmt(args)}) <- ${caller(this)}`;
      if (!seen.has(line)) { seen.add(line); console.log(line); }
    }
  });
}
hook("glViewport", a => [0, 1, 2, 3].map(i => a[i].toInt32()).join(","));
hook("glScissor", a => [0, 1, 2, 3].map(i => a[i].toInt32()).join(","));
hook("glEnable", a => "0x" + a[0].toUInt32().toString(16));
hook("glDisable", a => "0x" + a[0].toUInt32().toString(16));
console.log("tracing GL viewport/scissor");
