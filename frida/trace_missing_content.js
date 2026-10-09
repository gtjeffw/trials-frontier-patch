// Log every content file or texture the game asks for but cannot find (each name once).
// datapack::DataFilePack::searchFile(char const*, int&) -> nullptr when missing;
// Gfx::TextureManager::getTextureIdByFilename(char const*, bool) -> -1 when missing.
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_missing_content.js   (stay attached)
const base = Process.mainModule.base.sub(0x100000000);
const ts = () => new Date().toISOString().slice(11, 19);
const seen = new Set();
function report(kind, name, ctx) {
  const key = kind + " " + name;
  if (seen.has(key)) return;
  seen.add(key);
  const fr = Thread.backtrace(ctx, Backtracer.ACCURATE).slice(0, 4).map(DebugSymbol.fromAddress)
    .filter(s => s.moduleName === "TrialsFrontier").map(s => s.name).slice(0, 2).join(" < ");
  console.log(`${ts()} MISSING ${key} <- ${fr}`);
}
Interceptor.attach(base.add(0x10000a30c), {
  onEnter(a) { this.name = a[0].isNull() ? "(null)" : a[0].readUtf8String(); },
  onLeave(r) { if (r.isNull()) report("file", this.name, this.context); }
});
Interceptor.attach(base.add(0x100051268), {
  onEnter(a) { this.name = a[1].isNull() ? "(null)" : a[1].readUtf8String(); },
  onLeave(r) { if (r.toInt32() === -1) report("texture", this.name, this.context); }
});
console.log("missing-content tracer attached");
