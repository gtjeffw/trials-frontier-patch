// Print the engine's render size, touch-screen dimensions and touch scale (= render_w / touch_w, integer).
const base = Process.mainModule.base.sub(0x100000000);
const rd = a => base.add(a).readS32();
console.log(`render(0x100f2ada0..)=${rd(0x100f2ada0)} ${rd(0x100f2ada4)} ${rd(0x100f2ada8)} ${rd(0x100f2adac)} ${rd(0x100f2adb0)}`);
console.log(`touchDim=${rd(0x100f2adb4)}x${rd(0x100f2adb8)} touchScale=${rd(0x100f2adbc)}`);
