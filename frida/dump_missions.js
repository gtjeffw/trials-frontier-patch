// Read-only dump of the player's mission state: available ids, active records (id + flags), solved flags.
// Layout (7.9.0): PlayerProgress = m_player + 0x2300; available u16[64] at +0; active records 0x3c bytes x 64 at
// +0x80 (u16 id, u8 flags: bit0 cooldown, bit2 temporarily disabled); solved flag bytes at m_player + 0x3280 + id.
const base = Process.mainModule.base.sub(0x100000000);
const player = base.add(0x100f2ed90).readPointer();
const prog = player.add(0x2300);
const avail = [];
for (let i = 0; i < 64; i++) { const v = prog.add(i * 2).readU16(); if (v) avail.push(v); }
const active = [];
for (let i = 0; i < 64; i++) {
  const r = prog.add(0x80 + i * 0x3c);
  const id = r.readU16();
  if (id) active.push(`${id}(flags=${r.add(2).readU8().toString(2)} raw=${Array.from(new Uint8Array(r.readByteArray(16)), b => b.toString(16).padStart(2, "0")).join("")})`);
}
const solved = [];
const f = new Uint8Array(player.add(0x3280).readByteArray(520));
f.forEach((b, i) => { if (b & 1) solved.push(i); });
console.log("available: " + avail.join(" "));
console.log("active: " + active.join(" "));
console.log("solved: " + solved.join(" "));
