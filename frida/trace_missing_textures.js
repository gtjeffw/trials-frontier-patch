// Record texture lookups that fail (return -1): hash-based getTextureId and name-based getTextureIdByFilename.
// Lightweight on purpose: no backtraces, dedupe by key, stay attached (detaching has destabilised the game).
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_missing_textures.js
const base = Process.mainModule.base.sub(0x100000000);
const ts = () => new Date().toISOString().slice(11, 19);
const seen = new Set();
Interceptor.attach(base.add(0x100014348), {        // Gfx::TextureManager::getTextureId(unsigned int hash)
  onEnter(a) { this.h = a[1].toUInt32(); },
  onLeave(r) {
    if (r.toInt32() !== -1) return;
    const k = "hash " + this.h.toString(16).padStart(8, "0");
    if (!seen.has(k)) { seen.add(k); console.log(`${ts()} MISSING ${k}`); }
  }
});
Interceptor.attach(base.add(0x100051268), {        // getTextureIdByFilename(const char*, bool)
  onEnter(a) { this.n = a[1]; },
  onLeave(r) {
    if (r.toInt32() !== -1) return;
    let n = "?"; try { n = this.n.readUtf8String(); } catch (e) {}
    const k = "name " + n;
    if (!seen.has(k)) { seen.add(k); console.log(`${ts()} MISSING ${k}`); }
  }
});
console.log("missing-texture tracer attached");
