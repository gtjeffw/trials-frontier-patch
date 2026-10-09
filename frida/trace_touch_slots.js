// Log the game's 2-slot touch table (UITouch* identities + flags) before/after each EAGLView touch callback.
// Reads plain memory only: inspecting PlayTools' touch objects from Frida crashed or deadlocked the game.
// Usage: frida -p <pid> -q -t 600 -l frida/trace_touch_slots.js
const base = Process.mainModule.base.sub(0x100000000);
const SLOTS = base.add(0x100f2a880);      // UITouch* slots[2]
const RECS = base.add(0x100f2a8b0);       // per-slot records, 0x1c bytes: u32 flags, ..., +0xc x, +0x10 y
function slots() {
  const out = [];
  for (let i = 0; i < 2; i++) {
    const r = RECS.add(i * 0x1c);
    out.push(`${SLOTS.add(i * 8).readPointer()}/f${r.readU32().toString(16)}@${r.add(0xc).readS32()},${r.add(0x10).readS32()}`);
  }
  return out.join(" ");
}
const impls = {
  began: 0x1000073a4, moved: 0x1000074c4, ended: 0x1000075c8,
};
let last = "";
for (const [phase, addr] of Object.entries(impls)) {
  Interceptor.attach(base.add(addr), {
    onEnter(args) { this.line = `${phase} set=${args[2]} before=${slots()}`; },
    onLeave() {
      const line = `${this.line} after=${slots()}`;
      if (phase !== "moved" || line !== last) console.log(line);
      last = line;
    }
  });
}
console.log("tracing touch slots; slots=" + slots());
