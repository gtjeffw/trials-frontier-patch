# Journal

Chronological record of what was done, how, and what came of it. Personal data (device IDs, account
names, save contents) is deliberately left out; it lives only in the private workspace.

Conventions: `$WORK` is the private workspace (here `~/Projects/trials-frontier-recovery`), never committed.
Addresses are unslid vmaddrs in TrialsFrontier 7.9.0 (Mach-O UUID D1B9B883-E309-3B03-A4C7-9638F6621A0E).

## 2026-10-08 — Backups

- Devices: iPhone 15 Pro (iOS 26.6.2) and iPad Air 2 (iPad5,4, iOS 15.6.1), both with Trials Frontier 7.9.0.
- Tools: `brew install libimobiledevice ideviceinstaller`.
- `ideviceinstaller list --user --xml` gave bundle id `com.ubisoft.redlynx.trialsfrontier`, data container
  ~10.8 MB (iPhone) / ~11.6 MB (iPad), app ~280 MB.
- Full unencrypted backups: `idevicebackup2 backup --full <dir>` (iOS asks for the passcode on the device).
  Unencrypted backups exclude the keychain and Library/Caches/tmp.
- `scripts/extract_app_domain.py` pulls `AppDomain-<bundle id>` out of a backup via `Manifest.db`
  (opened with `immutable=1`; it is in WAL mode).
- Manifest metadata gives real file dates: the iPad (main play device) has 102 own ghosts (2017–2018),
  the iPhone only 3; `player.bin` last written 2026-01-10 (iPad).

## 2026-10-08 — First look at the data

- Ghosts (`ghost_<player>_<id>.bin`): 16-byte header (u32 version, u32 hash, u32 raw size, u32 0) + zlib.
  v2 payload: u32 time ms, u32 samples; v3 adds a leading u32 (bike id). ~133 ms per sample.
  `scripts/list_ghosts.py`.
- `player.bin`: high entropy, no known header → obfuscated (decoded later).

## 2026-10-08/09 — App extraction (iPad)

- The live data container (adds caches/tmp; no extra ghosts) and the app bundle were copied from the developer's own
  iPad, which still had the game installed. Tools and procedure are kept in the private workspace.
- Finding: the executable is protected with FairPlay encryption on the device; the rest of the code is plaintext
  with full C++/ObjC symbols. Game code: `tr::`; engine: `mz::`, `mt::`.

## 2026-10-09 — Save format

- `tr::Player::load()` → `mt::file::SaveFile` with a `Protection` constant at 0x100af1ff0.
- Decoding (`scripts/decode_save.py`): XOR stream, key = 0x9D, `key *= 0x20B9` per byte (low byte used);
  then 16-byte header (version 114, fletcher32 checksum, uncompressed size) + zlib. Fixed key → saves are
  portable between devices (matches 2015-era save sharing).
- Scores (`scripts/extract_scores.py`, from `tr::Player::loadScores`): u32 count, then per record u32 id +
  60-byte `tr::PlayerScores` (faults, time ms, integrity copy `360000000 - time - faults*3600000`, bike).
  210 timed records; every overlapping ghost time matches exactly.

## 2026-10-09 — Content packs and names

- `.dat` packs (`scripts/unpack_datapack.py`): u32 magic, u32 count, u32 entry size (12); entries
  (u32, u32 offset, u32 name hash); file = 8-byte header (u32 size, u8 zlib flag) + payload.
- Name hash = `mt::String::getHashCode`: `x += n*c; n = (n & 0xffff)*18000 + (n >> 16)` (32-bit, signed chars).
- `/conf/levels.txt` (JSON, 382 levels: key, id, difficulty, medal times M0–M3, fault limits F0–F3) and
  `/gen/lang/english_strings.bin` (LOCF: u32 key hash, u16 length, text). `scripts/build_report.py`.
- Medal order confirmed from an in-game screenshot (silver = third tier).
- Ghost/score ids are leaderboard ids: `track | (0x10000 << (bikeClass-1))` for normal tracks; events use
  mission/server-assigned ids. The 30 June-2017 event ghosts are not described by 7.9.0 data.
- Downloadable content packs are all bundled in 7.9.0 (`data/TrialsMobile/*.dat`).

## 2026-10-09 — Unencrypted executable

- An unencrypted copy of the developer's own executable was made for analysis and patching; the helper used is kept
  in the private workspace, not in this repository. Hashes recorded in `patches/trials-frontier-7.9.0.json`.

## 2026-10-09 — PlayCover (macOS 26.5.1, Apple silicon)

- `brew install --cask playcover-community` (3.1.0, notarized).
- Run 1 (unpatched): crash at startup. `tr::UserTracker::sessionStart` → `ubisoftDeviceUniqueId` →
  `keyChainGetValueForKey` → `getBundleSeedID` → `-[NSString initWithString:nil]`: ad-hoc signed apps get no
  `kSecAttrAccessGroup`. PlayChain (already enabled) does not help.
  Fix: patch `bundle-seed-id-constant` (return @"unknown").
- Run 2 (patched): game starts; privacy-policy screen, clicks land in the wrong place.
  - Touch path: `-[EAGLView touches*]` store UITouch* in a 2-slot table (0x100f2a880) with position
    × `touchScale` (0x100f2adbc). Press/release pairing works.
  - `mz::TouchScreenDimensions::set(w, h)` (from `applicationDidBecomeActive:`) sets `touchScale =
    renderWidth / w` with integer division. Render size (0x100f2ada0) was 2732×2048 (PlayCover device model
    iPad13,8), touch size 1920×1080 (PlayCover window) → scale 1 instead of ~1.42×1.90.
  - Workaround: PlayCover custom resolution 1366×1024 → scale exactly 2. Set it in PlayCover's UI; editing
    the settings plist while PlayCover runs gets overwritten.
- With that, the tutorial level played to completion.
- Crash on menu music (`AVAudioPlayer initWithData` → AudioToolbox internal C++ exception → jump into
  0x134f7d2c0). Attributed to Frida having been attached and detached earlier (stale unwind state in the
  region the agent occupied); the next run without Frida did not crash there.
- After the map overview the image is drawn full size but only the bottom-left quarter is visible.
  glViewport stays 2732×2048 and no scissor is used, so it is a view/layer geometry problem.
  `-[EAGLView layoutSubviews]` deletes the framebuffer; `createFramebuffer` sets `contentScaleFactor` only
  when `UIScreen.scale` is exactly 2.0 or 3.0 and sizes the renderbuffer from the layer. Under investigation
  with `frida/monitor_view.js`.

### Debugging lessons (Frida on PlayCover)

- Attaching works without changing macOS security settings (ad-hoc signed, no hardened runtime).
- `frida -q` exits immediately unless `-t <seconds>` is given.
- Do not wrap PlayTools' touch objects in `ObjC.Object` (crash in `objc_class::demangledName`) or call
  methods on them from hooks (deadlock). Do not heap-scan (`ObjC.chooseSync`) on the main queue (hang).
- Detaching appears to leave the process crash-prone on the next C++ exception; stay attached per session.
- iOS apps on macOS use `/System/iOSSupport/.../OpenGLES.framework`; hook its exports, not macOS OpenGL.
