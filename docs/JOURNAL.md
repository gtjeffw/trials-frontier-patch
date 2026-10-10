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

## 2026-10-09 — Ads disabled

- Ad/analytics SDKs in the build: Google AdMob (rewarded + interstitial), Tapjoy, Domob (China only),
  AdColony, IronSource/Supersonic, AppLovin, HyprMX, Vungle, Facebook, Flurry, Upsight, AppsFlyer,
  Crashlytics/Fabric, plus Ubisoft's own tracking (`tr::UserTracker`, `mz::DNAManager`).
- The game's ad switchboard is `tr::AdInterface`. `Ads_enabled` (bundled config value 1) and
  `Interstitials_enabled` (absent from config → default 1) are read only in `tr::AdInterface::initiOS()`,
  which then starts AdMob ("Trials Interstitial End Run"), Tapjoy and Domob.
- `canShowInterstitial` decides from play counters only (no SDK check), so it is patched too.
- New patches: `ads-sdk-init-disabled` (initiOS → `ret`), `ads-no-interstitials`
  (canShowInterstitial → false), `ads-no-reward-videos` (isAdsAvailableToShow → false).
- Hypothesis to test: the end-of-run interstitial (AdMob is still live) caused the view relayout that left only
  the bottom-left quarter visible after the map overview.
- Patched executable sha256 121b5748…; .ipa reproducible (c7211d31…).

## 2026-10-09 — "Download needed" bypass

- After the tutorial the game blocked on "Download needed - Please Wait…".
- `tr::AdInterface::dlContentOk()` requires `tr::DLContentManager::isDLReady()` once the mission named by
  `DLContent_Lock_MissionId` is done. `isDLReady()` is false when the saved download list
  (`Library/Caches/dl_content.state`) is empty, and each entry must match `MainApp::m_versionInt`
  (so app updates and iOS cache purges invalidate it).
- The list comes from `https://s3.amazonaws.com/dlcontent_frontier_ios/<version><ext>/info.json`
  (`queryContent`); the bucket no longer exists (`NoSuchBucket`). Underscore bucket names can no longer be
  registered, so the name cannot be taken over.
- `GlobalData::initAdditionalDataPacks` loads 12 bundled extra packs plus `TrialsContentDL.dat`,
  `TrialsContentDL2.dat`, `TrialsContentOfferDL.dat` from the download cache; those three are lost (the iPad's
  Caches folder was purged; the iPhone's uncaptured ~9 MB might still hold them but is unreadable without a
  jailbreak). The game tolerates them being absent.
- Patch `dl-content-always-ready`: `isDLReady()` → `mov w0, #1; ret` (all 10 callers go through it).
- Patched executable sha256 79fb0c04…; .ipa 4eeddc49….

## 2026-10-09 — Scissor cropping fixed at the source

- At the saloon a character was cropped. Geometry monitor: window/view/layer/viewport constant. GL clip
  tracer: `glScissor(0,0,1366,1025)` from `Gfx::Transform::pushScissor/setScissor` (via
  `mz::MenuzComponentScroller::render`) on a 2732×2048 framebuffer → only the bottom-left quarter survives
  (same symptom as the earlier post-map cropping).
- The engine screen size (0x100f2ada0, set in `mz::SystemInit::init`) comes from
  `[[UIScreen mainScreen] currentMode].size` in `didFinishLaunching`. On iOS that is pixels. PlayTools hooks
  `UIScreenMode.size` (`hook_size` → `PlayScreen.sizeAspectRatio`) and with a custom resolution returns the
  window size in points (1366×1024); with the default resolution it returned 2732×2048. `nativeBounds`
  (also hooked) consistently reports window × scale.
- Patch `screen-size-from-native-bounds`: read the size from `[UIScreen mainScreen].nativeBounds` (15-instruction
  block rewritten in place; x24/x25 still hold the original selectors). With a 1366×1024 window this gives
  2732×2048, touch scale 2732/1366 = 2.
- Patched executable sha256 ea88702c…; .ipa 9ddeb08b….

## 2026-10-09 — Offline mode

- Rendering confirmed fixed by `screen-size-from-native-bounds` (saloon character no longer cropped).
- New-player nickname step = mission (`tr::MenuzMissionContentLoginName`, `tr::MenuzMissionTaskEnterName`).
  The name is stored locally (`OnlineData::setSilentLoginName`, prefixed `#TF-` for online use) and the task is
  solved locally (`MissionSolver::isTaskSolved`). Online use: `OnlineCore::onConfigurationLoaded` →
  `activateSilentLogin` → `makeAutoLogin`, i.e. a Ubisoft profile `#TF-<nickname>`.
- Server status (2026-10-09): `gamecfg-mob.ubi.com` → Houston gateway still serves the game config (gzip JSON:
  gamesrv-mob, iap-mob, download-mob, profile/leaderboard endpoints); Ubisoft account services up;
  `imotoheroz.redlynx.com:7003` no connection; `ingame-news.ubi.com` 404; DLC bucket gone.
- Patch `offline-mode`: `mz::NetworkChecker::getNetworkType()` → 0 (no network). ~100 callers incl. login,
  configuration, store, time service, offers, DL content. Watch for gameplay that is gated on connectivity
  (daily rewards, VIP, special-event timers, `PlayerProgress::getOpenedLevels`).
- `frida/trace_dns.js` logs hostnames resolved, to verify no Ubisoft traffic.

## 2026-10-09 — Nickname prefix and cross-promotion

- The nickname keyboard is the game's own (`mz::MenuzComponentKeyboard`, drawn keys, tapped with the pointer).
- It pre-fills `#TF-`: `subComponentReleased` prepends the C string "#TF-" (0x100bbe0ba) to the stored name; the
  prefix marks auto-created Ubisoft accounts and would show in mission dialogue offline. Uses: the prefill,
  `PopupStateKeyboard::componentReleased`, `MenuzStateOptions::componentReleased`,
  `UserNameValidator::checkName/compare` (3+ letters beyond the prefix's letters; bad_wordlist.txt prefixed).
  Patch `no-tf-name-prefix` empties the string; validation rules stay equivalent.
- DNS tracer with offline-mode: `cp-mob.ubi.com` resolved via libcurl when the name UI opened — cross-promotion
  bypasses NetworkChecker. Patches `crosspromo-init-disabled`, `crosspromo-no-interstitial`,
  `crosspromo-no-more-games` (all → `ret`).
- Still contacted at startup (to do): `graph.facebook.com` (Facebook SDK), `settings.crashlytics.com`
  (Fabric/Crashlytics), `use.fontawesome.com` (likely the privacy-policy web view).

## 2026-10-09 — Nickname crash and corrected fix

- With `no-tf-name-prefix` the game crashed on OK (KERN_PROTECTION_FAILURE, write to 0xc152a0):
  `PopupStateKeyboard::componentReleased` (silent mode) builds an mt::String whose buffer is the shared
  read-only "" literal (capacity 1) and assigns "#TF-" to it. The 4-char prefix forces a heap allocation; an empty
  one is copied in place into read-only memory. Lesson: changing string literals can break code that relies on
  their length.
- Replaced by: `nickname-plain-keyboard` (`useSilentLoginKeyboard` → `ret`; ordinary name keyboard, no prefix
  handling, no 3-letter/bad-word validation) and `nickname-no-prefill-prefix` (pre-fill reads "" via
  adrp/add to 0x100c152a0; copied into a std::string, so safe). The "#TF-" literal is back to original.

## 2026-10-09 — Nickname works; keyboard controls

- Nickname "entered via the in-game keyboard" works offline; Mac `player.bin` decodes (version 114, 29,096 bytes)
  and contains the name. No new lookups beyond the startup ones.
- The game has no GameController support, so keyboard play uses PlayCover keymapping (keys → touches).
- HUD buttons (fractions of the screen): throttle (0.921, 0.884), brake (0.779, 0.893), lean back (0.079, 0.893),
  lean forward (0.214, 0.903), restart (0.932, 0.065), pause (0.049, 0.060). The game tracks 2 touches, enough
  for throttle + lean.
- `scripts/make_keymap.py` writes `playcover/trials-frontier-keymap.plist` (PlayCover Keymap 2.0.0: HID key codes,
  xCoord/yCoord fractions, size in percent): ↑/W throttle, ↓/S brake, ←/A lean back, →/D lean forward,
  Space restart (tap = checkpoint, hold = full reset; PlayCover holds the touch while the key is down),
  Esc pause. Requires Keymapping enabled for the app in PlayCover.

## 2026-10-09 — Leaderboards; patch groups

- Keyboard controls confirmed working in PlayCover (keymap file is only read at game launch).
- Post-race "Leaderboards" shows "You're disconnected from Ubisoft…": `tr::LeaderboardManager` only shows
  server-fed, cached boards (`requestLeaderboard`, `addToCache`, `hasDataAvailableFor`); there is no local-only
  view, so pretending to be online would give an empty board. Left as is.
- Idea for later: fill the leaderboard cache locally (own best + saved `robot_ghost` opponents); a fan server would
  plug in at the same place.
- Patches now carry a `group` (`compat`, `privacy`, `offline`) and `apply_patches.py --groups` selects them, so a
  future fan-server build can swap the `offline` group without touching the others.

## 2026-10-09 — Economy group: no fuel use, unlimited gems

- New optional group `economy` (user's choice for offline play: no fuel, unlimited gems, coins unchanged so gems
  can still be traded for coins in the game's own way).
- Fuel: every race start/restart path calls `tr::ConsumableManager::isUnlimitedFuel(level)` (unlimited-fuel
  booster, consumable 0x27d). Patch `unlimited-fuel` → always 1.
- Items: `tr::PlayerItems` stores counts obfuscated: `stored = rol(value, 7) ^ 0xab1d4f5`, index = item*5 + sub.
  Item 0 = currencies (sub 0 fuel, 1 coins, 2 gems). `remove(key, n)` / `setItemCount` cap items 1..10 and 0x14
  at 9999.
- Gems: both `getItemCount` overloads jump to code caves that return 9999 for slot 2 and otherwise do the original
  load. Caves sit in the zero padding between the load commands and __text (0x100006e00/0x100006e20); PlayCover's
  inserted `LC_LOAD_DYLIB` (PlayTools) only extends the load commands to 0x1cc8. `ghidra/scripts/Unreferenced.java`
  was used to look for dead functions first (only 3, not trusted).

## 2026-10-09 — Offline mode split: gameplay sees "online"

- Symptoms with blanket offline-mode: no candy/collectibles in event levels; garage upgrades ("parts") refused;
  fuel counter does not show unlimited.
- `LoadingStateLevel::createGameWorld`: for each active mission, unless `online && AntiCheating::isValid()`, every
  special-event sub-mission on the track is `disableActiveMissionTemporarily`'d → collectibles removed.
  `SpecialEventManager::isCollectibleCollected` returns false offline.
- `AntiCheating::isValid()` = disabled || NTP confirmed (`NetworkClock isNtpUpToDate`); offline it is never
  confirmed. ~40 callers incl. `StoreItem::isEnabled`, `PlayerTimers`, daily quests, missions, VIP, garage.
- Garage (`MenuzStateGarage::componentReleased`, cases 0x2b start / 0x36 finish upgrade) requires online and
  (mission upgrade || isValid || bypass).
- The 114 `getNetworkType` call sites were sorted: communication (login, config, store, offers, ads, images, DLC,
  DNA, UPlay, leaderboards, support, review, share, header/profile buttons, dog house, options, PvP, weekly
  challenge) stay offline; 62 gameplay sites in 33 functions now read online (`bl getNetworkType` → `mov w0, #1`,
  patches `gameplay-online-*`). `anticheat-trust-local-clock`: `isValid()` → true. All in group `offline`.
- Call-site list: generated from the disassembly (`bl __ZN2mz14NetworkChecker14getNetworkTypeEv`), each verified
  to be a `bl` to 0x10036a9cc before patching.

## 2026-10-09 — Story stall after the mechanic: downloaded-texture gate

- After the mechanic's mission (repeated "mission complete" rewards in the saloon, then nothing to do): available
  and active mission lists empty (`frida/dump_missions.js`; PlayerProgress = m_player+0x2300: available u16[64],
  active records 0x3c × 64 at +0x80, solved flag bytes at m_player+0x3280).
- Unlock rule `u,1,<id>` = `isRewardCollected(id)` (= solved and no longer in active/available lists), not "solved".
  Next story mission 171 "Home Sweet Home" needs only 6's reward → satisfied.
- `addAvailableMissions(bool)` skips missions with flag bit 2 unless `TextureManager+0x2c > 0`; that counter only
  counts textures from downloaded packs (`initPack` index > 21). Bundled TrialsTexturesDL* packs are indices 1–21.
  Downloaded packs are gone → story stalls. Patch `missions-no-dl-texture-gate` (compat): `cbz` → `nop`.
- Saloon (`MenuzStateMissionHall::componentReleased`): collecting a completed mission's reward calls
  `addMissionRewards` + `addRewardCollected` + `closeCompletedMission`, then the villager is given his next
  mission. With 171 blocked he kept the finished mission, so claiming repeated the reward (likely explanation of
  the repeated mechanic reward; same root cause).
- The original game on a device whose cache was purged would hit the same "Download needed" + this stall today.

## 2026-10-09 — Content audit (what the lost downloads cost)

- Story resumes after `missions-no-dl-texture-gate`: shopkeeper's helmet mission played and a further mission was
  offered.
- Live content tracing (hooking `DataFilePack::searchFile` with backtraces) hung the game at ~300% CPU; switched to
  static auditing.
- Levels: `/level/` + the level's `F` field (e.g. `/level/dump/Prod1 Andreas 3.lvl`), hashed with the game hash →
  all 382 levels present (LevelPack1 189, LevelPack2 177, content 16).
- Texture packs (`textures.dat`, `TrialsTexturesDL*.dat`): header u32 0, u32 count, u32 entry size 24; entry
  = u32 size, u32 offset, u16 w, u16 h, u32 format, u32 name hash, u32. 2,567 textures bundled.
- 1,948 texture paths referenced by content files and the executable: 1,869 present (96%). Missing 79: ~30 not game
  content (web/ad URLs, gamepad icons, SDK friends UI, editor paths); ~45 cosmetic/event art (outfit icons for riders
  14/16/18/22/28/53, coin variants, event teasers: Rodeo, Treasure Hunt, KTM, PvP, daily quest, New Year's offer);
  a few world props (crate, village time capsule, desert rocks, KTM banner/poster).

## 2026-10-09 — Remaining startup traffic (static analysis)

- Sources of the startup lookups seen with `frida/trace_dns.js`:
  - Crashlytics: `[Fabric with:@[Crashlytics]]` at 0x1001313c8 in `didFinishLaunching` → `nop` (privacy).
  - Facebook SDK: `[[FBSDKApplicationDelegate sharedInstance] application:didFinishLaunchingWithOptions:]` at
    0x100131768 → `nop` (privacy).
  - Google Mobile Ads self-initialises at load; `-[GADNetwork enableRadioAccessTechnologyChecking]` (imp
    0x10077b160, found via `otool -oV` ObjC metadata) resolves www.google.com → `ret` (privacy).
  - Ubisoft geolocation: `[self requestIpLocation]` at 0x1001314cc (gamecfg-mob/profile → houston geoip; used by the
    GDPR popup's country) → `nop` (offline).
  - Houston: `tr::HoustonEnvironmentService::requestHoustonParameters` (from `MenuzStateMain::transitionEnter`, via
    the game's HTTP stack; gateway still answers) → `ret` (offline).
  - Ubisoft Mobile SDK (`MobileSDKAPI::Init::CommonInit` → `msdk_internal_InitThread`) base URL
    "https://gamecfg-mob.ubi.com/" → "https://127.0.0.1:9/" (offline). Init kept: it also sets up the local sqlite DB
    and IAP store data.
  - `_getCountryFromServer` is only called from `_initCrossPromo` (already disabled).
- New helper `ghidra/scripts/FuncInfo.java` (containing function + callers for an address).
- After installing: Facebook still resolved graph.facebook.com — its SDK (4.x/5.x) auto-logs app activation
  independently of the removed start call. New spec section `plist_patches` (applied by `build_ipa.py --spec`, plist
  re-serialised as sorted binary for reproducibility): `facebook-no-auto-app-events` sets
  `FacebookAutoLogAppEventsEnabled = false` in Info.plist (privacy).
- Result: in 30 s after launch the only lookup is 127.0.0.1 (the Mobile SDK's redirected base URL).

## 2026-10-09 — Restored iPad profile; missing-texture crash guard

- Swapped in the restored iPad profile (Documents: player.bin, 102 ghosts, 385 robot ghosts, friend cache,
  screenshots; kept the Mac's msdk files). `Player::checkSavegameIntegrity` has no device check (repairs only).
  Fresh profile backed up in the private workspace.
- Starting a level crashed: `tr::BgRenderer::renderBackDrop` → `Gfx::TextureManager::bindTexture` on a texture slot
  that was reserved but never set up (null vtable) because its pack (downloaded TrialsTexturesDL.dat) is gone;
  likely the missing desert backdrop rocks.
- Patch `missing-texture-guard` (compat): bindTexture's lazy-load call goes through a cave (0x100006e40) that skips
  loading when the vtable is null and still calls `TEXTURE_HW::bind` (binds nothing) → object invisible, no crash.

## 2026-10-09 — Black levels: bundled texture packs not loaded

- With the restored iPad profile, Flower Hills and Frog Village rendered mostly black (after the texture guard).
  A lightweight tracer of failed `getTextureId` / `getTextureIdByFilename` lookups (`frida/trace_missing_textures.js`,
  no backtraces) showed swamp textures missing by name — yet they are in the bundled `TrialsTexturesDL_swamp.dat`.
- `initTextureManager` loads `textures.dat`, then 21 packs from a hard-coded suffix table at 0x100efb270
  (`.dat, _bikes0-3, _homeshack0/1, _fusion, _slotmachine0/1, _villagers0/1, _offericons, _cave, _maptiles(1),
  _special_event, _snow, _extraoutfits, _crazybikes, _dailyquest`), then any `TrialsTexturesDL_*.dat` that
  `findFilePacks` lists in save-path type 6 = `Library/Caches/DLC`. Bundled but not in the table: `_swamp`,
  `_moon` (bundle root), `_chipshop_extra`. They only ever worked via downloaded copies in Caches/DLC (purged on the
  iPad; never present on a fresh install now).
- Content packs: `initAdditionalDataPacks` table (0x100efb318, 12 names) includes Swamp/Snow/Cave but not Moon.
- Verified: copying the three texture packs into the container's Caches/DLC fixes Flower Hills and Frog Village.
- Made repeatable: spec `dlc_folder_packs` + `scripts/install_playcover.py` (also installs the .ipa and keymap).
  A self-contained binary fix (load them from the bundle) is possible later but needs extending a fixed-size table.
- Installer made generic: spec `pack_tables` (texture table 0x100efb270 ×21, content table 0x100efb318 ×12) and
  `dlc_content_names`. `install_playcover.py` reads the tables from the user's executable, copies every bundled
  `TrialsTexturesDL*.dat` not in the texture table (header-checked) to Library/Caches/DLC, accepts
  `--dlc-from <folder>` for packs saved from a device's download cache (texture packs + TrialsContentDL/DL2/OfferDL),
  and reports content packs this build cannot load (here: TrialsContentExtraDL_Moon.dat, one 60 KB object file; the
  "moon" tracks themselves are normal levels). `--dry-run` shows the plan.
- `TrialsContentExtraDL_Moon.dat` holds one file, `/gen/3d/env/moon/bg/dome.b3d`, referenced by
  `/resource/moon_00_bg.txt` (moon environment background; `BgRenderer::parseDataFile` calls
  `__iosShowFatalError("Cannot open file: ")` when a mesh is missing). It is not in the 12-name content table, and
  content packs are only otherwise opened from Library/Caches/DLC by three fixed names. The installer now puts such
  packs under a free "alias slot" name from the spec (`dlc_content_alias_slots`: `TrialsContentOfferDL.dat`, whose real
  pack — store offers — is lost); a real pack supplied via `--dlc-from` takes precedence. Game starts cleanly with it.

## 2026-10-09 — Level files decoded; environments per level

- Level files use the default `SaveFile` Protection (0x100aed960: seed 0x97, mult 0x1F49) + 16-byte header (+ zlib);
  body = chunk stream with LE u32 tags: `TRGO`, `HEAD` (0x20-byte LevelHeader: u16 version 3..30, byte 4 = object/
  environment pool, byte 6 = variant), `META` (source level name), `VISU`, `PHYS`, `TRIG`, `JOIN`, `BLOB`, `EFCT`.
- `scripts/level_info.py`: every level with its environment and pack. 382 levels: desert 83, city 68, village 53,
  cave 42, swamp 42, snow 48, happy 46, moon 0. Flower Hills (1152) is `swamp_02` — explains the black level.
  No level uses `snow_01` (the only environment whose `_bg.txt` is missing) or `moon_00` (event-only).

## 2026-10-09 — Online services probe (for an in-app loopback server)

Goal: race own ghosts and show FRIENDS/GLOBAL leaderboards without Ubisoft, via a local server (Mac prototype first,
later an in-app loopback server). Static analysis only.

- Transport: the engine (`mz::NetworkCoreIPhone`, `_NETWORK_makeRequest` 0x1001dcabc) uses `NSURLConnection` with an
  absolute URL, headers and a GET/POST/PUT/DELETE body. It fails immediately if `getNetworkType()` is 0, which is what
  our `offline-mode` patch returns, so every engine request currently errors locally. Info.plist has
  `NSAllowsArbitraryLoads`, so plain `http://127.0.0.1:<port>` works. The Ubisoft mobile login library (`ubimobile`,
  statically linked) uses its own bundled libcurl.
- Base URLs:
  - Ubiservices: string constant `https://public-ubiservices.ubi.com` (fileoff 0xbc834e), used as
    `%s/v1/applications/%s/configuration`, `%s/v1/profiles/sessions`, `%s/v1/profiles/%s`, `%s/v2/profiles/me/friends`.
    Requests carry `Ubi-AppId: 4b8b5f28-3561-4195-9dc8-c450aca960ae`.
  - Game server: NOT a constant. `OnlineUbiservices::parseConfigurationJson` (0x100317904) takes it from the app
    configuration response: `configuration.sandboxes[]` entry with `friendlyName` `triag_ip_lnch61_a_ws` (or
    `triag_ip_lnch_a_ws`) → its `url` → `OnlineCore::setserverAddress` (inline 64-byte buffer at OnlineCore+0x28,
    trailing `/` stripped). Requests are `"%s/%s/<path>"` with `"public"` as the second part.
  - ubimobile: network time from `http://gamecfg-mob.ubi.com/profile/?epoch=1` (`Server-Time:` header), account
    calls with `Authorization: UbiMobile_v1 t=…`, `Ubi-AppId`, JSON bodies.
- Gate for every game-server request, `OnlineCore::checkGameServerConnection` (0x1001dae4c), returns 0 only if: a
  server address is set; `OnlineAuthentication::hasAccess(access)`; a ticket is present (m_authentication+0x10,
  m_authentication = 0x100f43f80); `getNetworkType() != 0`; `OnlineUbiservices::m_configurationState == 2` (config
  fetched). Otherwise 3/5/0xb → "Could not connect to game server".
- Authentication (`OnlineAuthentication`, two back ends):
  - Mobile/silent (`OnlineAuthenticationMobile`, access flags 0xfff9f → includes leaderboard access 2): reads
    accounts `ubiacNN` from the keychain/iCloud KV (`ubimobile_getAllExistingAccounts`), creates one if needed
    (`ubimobile_createNewAccount*`, generated credentials + HMAC with network time), then gets a ticket
    (`ubimobile_getTicketForAccount*`). The result JSON must contain `ticket`, `profileId`, `nameOnPlatform`
    (`parseTicketData` 0x10013a168); profileId/name are copied into the player, then
    `setAuthenticated(ticket, len, 3)` → state 5.
  - Uplay (`OnlineAuthenticationUPlay`, the "Connect" button / web UI) → `onAuthenticationComplete` →
    `finishLoginSequence`.
  - Every authenticated engine request gets `Authorization: Ubi_v1 t=<ticket>` (`OnlineCore::addAuthentication`);
    tickets are renewed after 0x1518 s (`PUT /v1/profiles/sessions`).
- Leaderboard/ghost requests (all `<server>/public/…`):
  - `playerstats/v1/ranking/<lb>?around=<profile>,<n>` / `?range=a,b` / `?players=…` (requestRelativeLeaderBoard
    0x1002db7f4, requestLeaderBoard, friends)
  - `resultservice/v1/replay_id` POST `{"profile_id","track_name":"track<id>","drive_time","faults","bike"}`
    (GhostQueryObject::queryGhostShared 0x1002d8244)
  - `resultservice/v1/replaydata?track_id=<id>`, `userstorage/v2/content/<type>/<id>/payload`,
    `resultservice/v1/enhancestats/track<id>`, `match/v1/robot?…`

## 2026-10-09 — `local-services` patch group (opt-in) + local server prototype

- Of the 115 `getNetworkType` call sites, 62 were already forced online (gameplay); the other 53 are ads, analytics,
  store, offers, support, images, DL content and the online stack. Instead of turning the network check on
  globally, the new opt-in group `local-services` (spec `optional_groups`; `apply_patches.py --with local-services`)
  forces only the online-stack sites it needs and adds two hard guards:
  - `local-services-loopback-only-*`: `_NETWORK_makeRequest` (every engine HTTP request) calls a cave
    (0x100006e80) instead of `getNetworkType`; the request proceeds only if its URL starts with
    `http://127.0.0.1:`. Also covers the 62 gameplay sites forced earlier.
  - `local-services-dns-guard-*`: the `_getaddrinfo` stub (0x100ae1604) branches to a cave (0x100006d00) that calls
    the real function (GOT 0x100d030a0) only for host `127.0.0.1` and returns EAI_NONAME otherwise. Covers libcurl
    (mobile login library), the ubiservices C++ SDK sockets, GCDAsyncUdpSocket and SNTP.
  - Redirects (same-length C strings): Ubiservices base, the mobile login URL (+UAT) and the network-time URL →
    `http://127.0.0.1:7979`. The game-server URL comes from our configuration response.
  - Forced online: `OnlineUbiservices::getApplicationConfiguration`, `OnlineAuthentication::login/update`,
    `OnlineCore::checkGameServerConnection`, `MenuzComponentLeaderboardList::update`.
- Mistake caught: the first DNS cave was placed at 0x100006f00, inside `__text` (which starts at 0x100006ee8), and
  the spec recorded the overwritten code as "original". `apply_patches.py` now refuses any "(zero padding)" cave
  that is not all zeros or ends past the `__text` start (`macho.text_section_offset`).
- Default build unchanged (sha256 28f0738…); `--with local-services` build recorded under
  `sha256.patched_executable_with`.
- Mobile login details: account creation and ticket both `POST /v2/profiles/sessions` body `{}` with
  `Authorization: UbiMobile_v1 t=<base64>`; creation requires `"environment":"Prod"` and `nameOnPlatform`; the
  ticket reply needs `ticket`, `profileId`, `nameOnPlatform`. Network time = `Server-Time:` header (epoch seconds,
  atof). Accounts are stored in the keychain as `ubiacNN`.
- `server/local_services.py`: stdlib HTTP server on 127.0.0.1:7979 that logs every request and answers
  configuration, network time and sessions (profile id/name read from the container's player.bin); everything else is
  404 + `UNHANDLED`. `scripts/netwatch.py`: polls `lsof` for the game process and marks non-loopback sockets `LEAK`.
  Baseline (default build, running): no sockets at all.

## 2026-10-09 — Own ghosts race again (local-services, first end-to-end success)

- First run: only the configuration request; no login. Restored Uplay-linked saves never auto-login
  (`OnlineCore::makeAutoLogin` only calls `loginSilent` for login type 2; `onConfigurationLoaded` otherwise waits
  for the Uplay web login). Added `local-services-auto-login` (0x1001d9ebc `ldr w20, [x8, x9]` → `mov w20, #2`).
- Second run: ~1,800 account creations in 30 s. The mobile login library checks the creation reply with
  `strstr("\"environment\":\"Prod\"")`; Python's default JSON (`"environment": "Prod"`, with a space) failed it, so
  the account was treated as UAT, deleted (`ubimobile_DO_NOT_CALL_IN_RELEASE_BUILD_deleteAccount`) and recreated.
  The server now sends compact JSON. Keychain storage itself works under PlayCover.
- Note: Cmd+Q / closing the window in PlayCover leaves the process running; quit with
  `osascript -e 'tell application id "com.ubisoft.redlynx.trialsfrontier" to quit'` (graceful; the game saves).
- Third run: login OK, GLOBAL shows the player's own entry (from the save's score table), names resolve via
  `GET /v1/profiles?profileId=`, and **racing the own ghost works** (`POST resultservice/v1/replay_id` →
  `{"replay_id":N}` → `GET userstorage/v2/content/ghost/N/payload` = the ghost file bytes as stored in Documents).
  Tracks without a saved ghost (e.g. Flower Hills) keep the race button disabled (replay_id 0). netwatch: only
  127.0.0.1:7979.
- Requests seen but not answered yet (404, harmless): `match/v1/robot`, `resultservice/v1/enhancestats/batch_update`
  (re-submits stored results), `targeting/v1/configuration|condition_items|vip_validation`, `pvp_matches/v1/pvp_init`,
  `liveevents/v1/weekly_track_system/basic_info` (retried every ~11 s), `gift/v1/gifts|get_gifts`.
- Ghost upload, as the original game did it: `IngameStatePostRace::sendToOnlineLeaderboard` submits only when the
  run set the "new best" flag (Player+0x6ea8; server setting 0xd69745a5 = 1 would force every run), with the right
  bike tier and outside events: `POST resultservice/v1/enhancestats/track<id>` `{"updates": [ {…} ], checksum}`.
  Only if the reply's first update has `"updated"` ≠ 0 does `OnlineResult::onResultSent` call
  `OnlineGhostManager::submitGhostFile("ghost_<hash>_<lb>.bin")` (drive time must match) → user-storage search →
  add/send data. `OnlineGhostSync` re-uploads a local ghost when the server's stats match it. So uploads are
  best-only on both sides; the server should confirm only real improvements (fewer faults, then less time).
- Avatars: `getUserPicture` / `getDefaultUserPicture` URLs (Ubisoft CDN) redirected to
  `/avatars/<profileId>/default_146_146.png` and `/avatars/fallback_146_146.png`; the server serves
  `<--avatars dir>/<profileId>.png` / `fallback.png` (personal pictures stay outside the repo).

## 2026-10-09 — Score reader fix; result submit and ghost upload

- The Cave vanished from GLOBAL after login: the score-table reader required PlayerScores byte 0 = 0xff and a
  non-zero leaderboard id. The game changes that byte after a race and, once logged in, adds a `global_stats` record
  (id 0), so the real table (now 241 records at raw offset 19016) was rejected and a shorter false match used.
  Fixed in the server and `scripts/extract_scores.py`: integrity copy only, choose the table with the most timed
  records. The save itself was intact.
- Server store (`<container>/Library/LocalServices/store.json` + `ghosts/<id>.bin`), seeded from the save and the
  player's ghost files. Result submit `POST resultservice/v1/enhancestats/track<lb>` → `{"result":{"updated":0|1}}`
  (better = fewer faults, then less time); `batch_update` → `{"status":[{"track_name":…}]}` (marks synced).
- Ghost upload as the game does it (`OnlineGhostManager::submitGhost` → `GhostQueryObject::queryGhost(int)`):
  `GET resultservice/v1/replaydata?track_id=<lb>` → `{"content_id":N}` (existing content → PUT payload to it) or 0
  → `POST userstorage/v2/content/ghost` (metadata `{ "metadata" : {"track_id","drive_time","checksum","version"}}`)
  → `{"contentId":N,…}` → `PUT …/content/ghost/N/payload` (ghost bytes) → `PUT …/content/ghost/N` (metadata).
  First real PB (Vault Crawl, 72 F, 4:05.166) was accepted as NEW BEST but the upload stopped at the then-404
  `replaydata`; fixed. The same request after `playerstats/v1/stats/track<lb>` is `OnlineGhostSync` re-sending a
  local ghost whose time matches the server's.
- Ghost acceptance: a payload is stored only if its drive time (ghost body: u32 bike, u32 drive time for version 3)
  equals the player's current best result for that leaderboard, or (no result) is not slower than the held ghost.
- PlayCover: Cmd+Q / closing the window does not end the process (relaunch resumes). True quit:
  `pkill -x TrialsFrontier` (SIGTERM; the save decodes fine afterwards). One session stopped accepting clicks while
  still rendering the map (cause unknown).

## 2026-10-09 — Other riders on GLOBAL: downloaded opponents and 2019 world records

- Friends: the iPad's `friend-17FE8523.cache` (default SaveFile Protection) holds an empty list (written
  2020-10-10); nothing to restore.
- Opponent ghosts the game downloaded for "beat this rider": `Documents/robot_ghost-<HASH>-<LBHEX>.robot` (385 files,
  383 riders, 150 leaderboards; ghost container v3, body u32 bike, u32 drive time) and avatars
  `robot_image-<HASH>.robot` (default Protection, 16-byte header, `OBOR` + 12 bytes + 146×146 PNG). HASH =
  getHashCode(profile id), so riders are anonymous except where the save keeps a name: a name followed 129 bytes
  later by its profile id (two opponents are named this way). The server imports them once
  ("Rider <HASH>" under a stable uuid5 id; known ones under their real id/name), with ghosts and avatars; faults are
  unknown (0).
- 2019 world records: dutscher/trialstrackmap (MIT) `database/wr/wrrider.json` (2019-12-11 snapshot; 118 riders,
  361 tracks × Android/iOS × normal/donkey/crazy) + `database/trackdata/ids.json` (site id → game level id "oid";
  JSON with `//` comments). Mapping verified: all 375 site tracks' medal times equal the game's M0–M3. Categories:
  normal = `track<id>`, donkey = `track<id|0x10000>` (bike 19), crazy = `track<id|0x100000>` (bikes 10/11), matching
  the save's own leaderboards. Imported with `--world-records/--world-record-ids` (2158 results); the data stays in the
  private recovery folder with its licence and source note, not in this repo. No ghosts for these.
- FRIENDS asks only for the player's own id, so it shows just the player; GLOBAL shows everyone around the player.

## 2026-10-09 — Opt-in `coins-for-gems` content patch

- In 7.9.0 the coin packs are App Store products only: `/conf/store_2_coins.txt` (content.dat, hash a5e43c11)
  lists `com.ubisoft.redlynx.trialsfrontier.caps1`–`caps6` (60k–5M coins, item IID 0 / IL 1) with no in-game price
  (PH 0, PS 0), so the shop needs StoreKit and shows the network message. Gem packs `diamonds1`–`6`
  (`/conf/store_1_gems.txt`) give 200, 450, 600, 1000, 2200, 5800 gems at the same price tiers.
- Gem-priced items without an App Store ID already exist (track packs, PH 400/600) and are bought in-game
  (`StoreItemManager::tryPurchaseItem` → `purchaseItem`). The opt-in group `coins-for-gems` (spec
  `content_patches`, `build_ipa.py --with coins-for-gems`) empties the six IDs and sets PH to the matching gem-pack
  amount.
- Datapack index entries are {unpacked size, offset (relative to the data area), name hash}; files are
  {u32 stored size, u8 compression, `de c0 de`} + data. `scripts/datapack.py` appends the edited file and repoints
  only its entry; verified: one index entry changed, all other files byte-identical, edited JSON strictly valid.

## 2026-10-09 — Level audit; opt-in `open-all-levels`

- Map placement: every level in `/conf/levels.txt` has X/Y; `LevelMetaData::isAvailableOnMap` = X²+Y² < 8000²
  (constant 0x100af304c = 64e6). 376 of 382 are inside; 6 sit at (-10000,-10000): Sine City, Hill Climb, Bunnyhop
  ("hidden bunker tracks"), Rigged Roadway, Roadway ("Agent"), Collapsed Orchard (Rodeo). Only three spots are
  shared (two hold unnamed test levels, one two X-Games tracks at (-1,-1)); events did not replace existing spots.
- Markers are revealed in `Map::init` for `PlayerProgress::getOpenedLevels` (daily-experience rewards, robot missions,
  levels referenced by solved missions, levels with a score), `PlayerItems::getCraftingLevels` and purchased
  additional level packs. Items 170–199 call `PlayerItems::addRewardedLevel` (bought/rewarded tracks: slots 850–999,
  two u16 level ids per slot); items 200–219 are map pieces (slots 1001–1099: u16 level, u16 pieces).
- Decoded save: PlayerItems starts at raw offset 0x914 (slot = ror(stored ^ 0xab1d4f5, 7); coins = slot 1).
  `scripts/level_audit.py` classifies every level (raced / owned / pieces / hidden / off map / test level).
  Player after buying the Special Track Pack ~15 times (it re-rolls six unowned tracks until none are left): 201
  raced, 104 owned not raced, 1 with pieces (Dual Snowfest 2/10), 65 hidden (X-Games Minneapolis 38, Bunker tier 1
  16, Petrol Falls 5, Dakar 2, Halloween #2 2, Cave Dweller, Dark Machine), 5 off map, 6 unnamed test levels.
- `Map::init(MenuzStateMap*, bool)` calls the developer function `Map::cheatOpenAllLevels` (reveal every on-map level
  with a name localization) only when its bool is set: `tbz w20, #0` at 0x1002ce6bc. Opt-in group
  `open-all-levels` replaces it with `nop`.

## 2026-10-09 — Map fog and tiles; opt-in `orphan-levels`

- Map layer = levels.txt `L` (LevelMetaData+0x2d4; 0 main map: 206 levels, 1 ferry island: 176); `Map::revealMarker`
  only reveals markers of the current layer.
- Background tiles `/MENUZ/MAP/LAYER_<L>/MAP_BG_<row>_<col>.PNG` (Map::initTileData; grid 5×7 → 7×8 once the mission
  in GlobalSetting `DLContent_Lock_MissionId` is solved). 512 units each, tile (r, c) at x = −1792 + 512c,
  y = −768 + 512r (Map::render constants 0x100af7bd0/7bcc/0x100ae69b4). Art present: main map rows 0–4 × cols 0–6
  (maptiles packs + textures.dat), ferry 5×5; the rest of the 7×8 grid has no art in 7.9.0.
- Fog of war (`Map::renderOffscreenFogOfWar`): an offscreen mask lit by a 300-unit soft circle at each revealed
  marker (state 1/2) and village; a per-tile flag (Map+0x7be, index x/512+4, y/512+2) picks plain vs. fog shader.
  So fog lifts wherever a revealed marker sits. With every level revealed the main map's column 6 (x 1280–1792; the
  user's "right strip") and the top-left corner stay fogged though they have art (y grows downward, as on screen).
- Opt-in group `orphan-levels` (content patch on `/conf/levels.txt`, new `level_position` op in
  `scripts/datapack.py`): Sine City, Hill Climb, Bunnyhop, Rigged Roadway, Roadway, Collapsed Orchard move from
  (−10000, −10000) to x 1530, y −560…1190 (350 apart). Top-left corner kept free for the unnamed test levels.
- Adjusted after user screenshots (≈0.6 px per map unit; Rotten Railway, Smelting Pots, Daredevil Paradise as
  references): at the camera's right limit the right-hand UI panel covers x > ~1370, so the orphans moved to x 1230,
  y −200…750 (190 apart), inside the fogged area east of the eastern sea route.
- Test: the orphans appear; Roadway and Collapsed Orchard start; Sine City, Hill Climb, Bunnyhop and Rigged Roadway
  show "watch the ad and get free gems". They have bike tier B = 255: `LevelManager::isCorrectBikeTier` treats that
  as any bike, but `MenuzStateMap::startLevel` needs `getBikeReadyCountForTier(B) > 0` (0 for 255) and otherwise
  shows the "need a tier N bike" message at string index (first tier message + 254) — an unrelated string. These
  were started by their event with a set bike. `orphan-levels` now also sets their B to 0 (new op
  `level_bike_tier`), the tier of most difficulty-1 levels (90 of 117).
- The four tier-255 orphans are the PvP special tracks (GlobalSettings `PVP_Special_Tracks` = 1211,1212,1233,1258;
  also why the PvP init list always ends with them); 255 = any bike (`IngameStateSelectBike::showBikes(255)` lists
  every bike). Replaced the tier-0 data edit with a cave (0x100006c00, hook at
  `UpgradeManager::getBikeReadyCountForTier` 0x100229aa0): for tier 255 return the sum of the ready counts for tiers
  0–2, which fixes `MenuzStateMap::startLevel`, `LoadingStateLevel::update` and `IngameStateHUD::restartWorld`.
- Opt-in group `dev-levels`: six unnamed test levels (files present in LevelPack1/2: Prod30 Maria 1, Flat,
  Prod45 Ukkis 1, Donkey lvl, Prod55 Maria 3, Prod58 Maria 5) get "<name> (dev)" in all eight `/gen/lang/*_strings.bin`
  tables (LOCF: 'LOCF', u8 1, u32 count, unsorted {u32 hash, u16 len, text}; new op `add_strings`) so
  `cheatOpenAllLevels` reveals them, and move from their shared spots into the column.
- Layout for all twelve: zigzag x 1180/1290, y −230 + 90 per row (orphans rows 0–5, dev rows 6–11).

## 2026-10-09 — Native local services (inapp/), parity with the Python server

- `inapp/` holds the same services in plain Objective-C (ARC; Foundation, CommonCrypto, zlib only):
  `TFSave` (save/ghost/robot formats, getHashCode, uuid5), `TFHTTP` (loopback HTTP/1.1 server, thread per
  connection, keep-alive; route table of (method, full-match regex) → handler), `TFServices` (store, imports, core
  routes, quiet catch-all), `TFLocalServices` (start-up; listens at once, requests wait until the store is loaded),
  `TFEntry` (dylib constructor: Documents/LocalServices, log `server.log`, optional world-record and avatar files
  from the app bundle's `LocalServices/`), `cli/tfserver.m` (macOS command-line build for tests/development).
- Feature modules (`TFServiceModule`, listed in `TFLocalServicesModules()`) register routes after the core and
  before the "not offered" catch-all — the place for a future daily robot-challenge module.
- `scripts/build_inapp.py`: `libTFLocalServices.dylib` (arm64, iOS 15+, install name
  `@executable_path/Frameworks/…`) and `tfserver` (macOS). Builds without warnings.
- `tests/test_parity.py`: runs both servers on a copy of the player's Documents, sends 36 scripted requests
  (login, leaderboards in all query forms, results worse/better/batch, ghost search/download/upload/refusal/metadata,
  names, avatars, quiet and unhandled routes) and compares status + body (timestamps and port ignored) and the final
  stores: PASS. Both servers now break ties explicitly (leaderboards by profile id, ghosts by content id).
- Bug found by the first smoke test: route handlers held the services object weakly and nothing else kept it after
  start-up, so every JSON reply was `{}`; kept for the process lifetime now.
- The Python server's default store moved to `Documents/LocalServices` (same as in-app; a store in
  `Library/LocalServices` is moved once).

## 2026-10-09 — Embedded server running in the game (PlayCover)

- Opt-in group `embedded-server`: LC_LOAD_DYLIB `@executable_path/Frameworks/libTFLocalServices.dylib` (80 bytes at
  0x1c68, after the 65 original load commands; header ncmds 65→66, sizeofcmds 0x1c48→0x1c98). `build_ipa.py`
  adds spec `bundle_files` for selected groups (`--inapp <dir>`), plus the player's own `--avatars` and optional
  `--world-records/--world-record-ids` into the app's `LocalServices/`.
- PlayCover installs it, signs the library ad hoc and appends its PlayTools load command after ours. On launch the
  game process itself listens on 127.0.0.1:7979; the store moved from Library/LocalServices to
  Documents/LocalServices with everything in it (2759 results, 493 ghosts, 501 riders); login, configuration and the
  usual start-up requests are answered; netwatch: loopback only. The Python server is now only for development
  (build without `embedded-server`).

## 2026-10-09 — `build.py` and README

- `build.py`: one command from the player's own `.app` to an installed game: picks the executable (unencrypted,
  `--decrypted`, or encrypted + `--page`), applies the default groups plus `--server embedded|external|none` and
  `--with` options, builds the in-app library for `embedded`, packages the `.ipa` (`--avatars`, world records) and
  with `--install`/`--keymap` runs `install_playcover.py`. Verified: the embedded build is byte-identical to the
  installed one (ipa sha256 c1b6f0a8…, including the freshly compiled library); `external` and `none` from the
  encrypted executable + page give the recorded executable hashes (a46fb1b…, 28f0738…).
- README rewritten for the current state (quick start, options, local services, development, getting the files).

## 2026-10-09 — A public 7.9.0 copy: same packs, 32-bit executable

- The only publicly posted 7.9.0 iOS copy found (details kept private) is decrypted
  (`cryptid 0`, no `SC_Info`) but its executable is a universal file with only an **armv7** slice (UUID
  7E096C5A-…), dumped from a 32-bit device. App Store copies are thinned per device: the developer's iPad copy has
  only arm64 (UUID D1B9B883-…, the one the patches target) and device-specific `Assets.car`.
- All 42 `.dat` content packs are byte-identical to the iPad copy (441 of 445 files identical; different:
  executable, `Assets.car`, `Info.plist`, `_CodeSignature/CodeResources`).
- `build.py` now checks the executable before patching (architecture incl. universal files, Mach-O UUID) and fails
  with a clear message instead of a traceback; an explicit `--decrypted` takes priority over the app's own
  unencrypted executable. Public `.app` + own arm64 executable → the same patched executable (81f6703…) and the same
  content edits; the package differs from the own-copy build only in the artwork/plist/signature files above.

## 2026-10-09 — Download folder inside the app (compat: dlc-folder-in-bundle)

- Two path builders serve the download folder: `__getSaveFilePath` type 6 (listing, `GlobalData::findFilePacks`)
  and `mt::file::File::getAbsolutePath` case 8 (opening: `DataPack::open` → `openSaveFile(name, subtype 8)`),
  both NSCachesDirectory + "/DLC". First attempt patched only the listing: the game found the bundled packs but
  could not open them ("Cannot open TrialsTexturesDL_chipshop_extra.dat", crash). (`File::create` resolves
  subtypes 2/4/5/8 via getAbsolutePath; others as bundle resources via CFBundleCopyResourceURL.)
- Caves (compat group): 0x100006a00 for type 6, 0x100006b00 for getAbsolutePath case 8 (other cases unchanged);
  both return `[[NSBundle mainBundle] resourcePath]` (+ "/DLC"), using only existing references: NSBundle classref,
  `mainBundle`/`stringByAppendingString:`/`objectAtIndex:` selrefs, CFString @"/DLC", stubs objc_msgSend,
  sel_registerName ("resourcePath" has no selref), NSSearchPathForDirectoriesInDomains.
- `scripts/dlcpacks.py` (selection formerly in install_playcover.py); `build_ipa.py` puts the packs into
  `TrialsFrontier.app/DLC/` (spec `bundle_dlc`; `--dlc-from` for a player's own downloaded packs);
  `install_playcover.py` copies to Library/Caches/DLC only with `--caches-dlc` (old builds).
- Verified in PlayCover with Library/Caches/DLC moved aside: the game has all four packs open from the app's
  `DLC/` (swamp, moon, chipshop_extra, Moon content as TrialsContentOfferDL.dat). Recorded hashes updated.

## 2026-10-09 — iPhone/iPad build tooling

- Opt-in `file-sharing` (plist: UIFileSharingEnabled, LSSupportsOpeningDocumentsInPlace); `build.py`/`build_ipa.py`
  `--bundle-id`, `--display-name` (install next to the original, own data container).
- `scripts/sign_ios.py`: signs a built .ipa with the player's own (free) Apple development account: finds the
  provisioning profile for the bundle id that Xcode created, the matching identity, writes entitlements from the
  profile (exact application-identifier and keychain group), embeds the profile, signs `Frameworks/*.dylib` and the
  app, verifies, writes the .app and a signed .ipa. The original bundle has no extensions/frameworks of its own.
- `scripts/ios_device.py`: devicectl wrapper — devices, install, push-data (player.bin, ghost_*, robot_*,
  LocalServices/ from the PlayCover copy into the app's Documents), pull-data (backup), list.
- First iPhone install refused: the iPad copy's Info.plist carries App Store thinning's `UISupportedDevices`
  (iPad models only) → MIInstallerErrorDomain 86 DeviceNotSupportedByThinning. The unthinned app has no such key
  (UIDeviceFamily [1, 2]); compat plist patch `no-device-thinning-list` removes it (build_ipa.py plist patches can
  now `remove` keys). Signed with the player's free personal team (profile valid 7 days) and installed on an
  iPhone 15 Pro (iOS 26) next to the original app.
- `ios_device.py push-data` stages the files and copies them in one devicectl transfer (folder copies work;
  1747 files in seconds), replacing the app's Documents.
- iPad Air 2 (iOS 15.6.1): devicectl (CoreDevice) does not manage devices below iOS 17 ("unavailable"). After running
  any app on the iPad from Xcode once (registers it in the free profile), the same signed .ipa installs with
  `ideviceinstaller -u <udid> install <signed.ipa>` (libimobiledevice 1.2 syntax). Data: on this jailbroken iPad via
  SSH + tar into the app container (found by bundle id in `.com.apple.mobile_container_manager.metadata.plist`);
  for other iOS < 17 devices the `file-sharing` option lets players drag the files in with Finder.
- Verified on both devices: "Trials Offline" starts with the copied profile, Flower Hills renders (bundled
  packs), leaderboards and ghost racing work through the embedded server (iPhone log: login, store load, replay).

## 2026-10-09 — Full screen in PlayCover

- PlayTools reports the screen as the configured window size × `customScaler` (nativeBounds) regardless of the real
  window; with `screen-size-from-native-bounds` the engine renders at that size and touches arrive in window
  points, so touchScale = 2 for any custom resolution. Tested: custom 1920×1080 (external display's size), full
  screen via the green button — touch, layout, keyboard joystick, races (donkey bike), leaderboards all fine.
  The 1366×1024 requirement is gone; per-axis float touch scaling would only matter for fractional scalers.

## 2026-10-09 — Robots ("Live Opponents") served locally

- Robots belong to A.N.B.A. (RobotmanManager / OnlineRobotMission: "repair memory blocks by defeating Live
  Opponents"), a side quest line, not the main story (mission data has no robot tasks; one EVENT_BEAT_GHOST event).
  `findOpponent` → `MatchMaking::getRobot` → `GET match/v1/robot?track_name=track<N>&range=&offset=` (type 0x47;
  `parseMatchMakingResult`: flat {player, drivetime, upgrades, data, score_value, replay_id}) →
  `OnlineGhostManager::getRobotGhost` → `GET resultservice/v1/robot_replaydata?track_id=&time=&player=` → saved as
  `robot_ghost-<getHashCode(player)>-<lb>.robot`, then name/picture via `/v1/profiles` and the avatar URL. Any
  failure → `RobotmanManager::onMatchMakingFailure` (next track), so missing robots never block.
  `match/v1/robot_v2?track_name=&score=&range=` (type 0x48, `OnlineMission::getMissionGhost`) = mission ghosts.
- Both servers now answer these from the store: other riders first (exact leaderboard, else same base track),
  closest just slower than the player's best (faster ones after; slowest if the player has no time; `offset` steps);
  the player's own ghost only if no one else has one; nothing → 404. Parity test extended (robot, own-only fallback,
  none, robot_v2, robot_replaydata): PASS.
- In play (PlayCover): the game took the robot, downloaded the ghost via robot_replaydata and saved
  `robot_ghost-<hash>-<lb>.robot` (the ghost format is accepted), then asked `GET /v1/profiles/<id>`
  (`OnlineUbiservices::getPlayerProfile`, one profile object, parsed by `parseProfileJson`) — added to both servers
  (parity: PASS). After that: robot → ghost → profile → avatar all answered (other rider on The Trebuchet) and the
  game stopped re-requesting (opponent accepted).

## 2026-10-09 — New players (no save yet) and a second PlayCover copy

- Both servers used to read the profile id and name from `player.bin` once at start; a fresh install has none. Now:
  no save → a random profile id kept in the store (`new_player_profile`), which the login returns (the game keeps
  the id it is given); the name is re-read from the save whenever `player.bin` changes (the tutorial's
  `MenuzMissionTaskEnterName` sets it), "Rider" until then; save imports skip a missing save. Parity test gained a
  new-player case (made-up id survives a restart, "Rider", first result, name from a save once one appears): PASS.
- `install_playcover.py --bundle-id` (and `build.py --bundle-id` passes it on): a second copy with its own data in
  PlayCover. Built "Trials Fresh" (`local.trialsfrontier.fresh`, embedded server, no options, no imported riders)
  to play the story from the start as a new player would. Only one copy at a time (both serve on port 7979).

## 2026-10-09 — History cleaned, licence

- `git filter-repo --replace-text`: the developer's profile name and two other players' names and id prefixes,
  which appeared in two earlier journal commits, are replaced in every commit (58 kept); author/committer moved to
  a GitHub noreply address. Searched all history afterwards: no names, profile ids, device ids or local paths left
  (only the game's application id and the standard UUID namespaces). MIT licence added.
- 2026-10-10: second pass: the site name of the publicly posted copy (one journal line) replaced in every commit;
  the repository names no download sources.

## 2026-10-10 — Ghost bundles: publish your own times and ghosts

- `scripts/ghost_bundle.py` with `export`, `check`, `publish`, `import`, `search`; format in `docs/BUNDLES.md`.
  A bundle = manifest + the game's own ghost files (+ avatar), published as a public GitHub repository with the
  topic `trials-frontier-bundle` (the topic search is the index until a collecting service exists).
- Identity without the profile id: the game's 32-bit hash (the name of downloaded-opponent files, so a rider's
  bundle merges with the "Rider <hash>" opponents in everyone's saves) plus a salted sha256 for collisions.
  Optional SSH signature over the manifest (which lists every file's sha256), checked against
  `github.com/<publisher>.keys`, as the basis for any later claim of a rider's records (Ubisoft accounts cannot be
  relied on: many were purged).
- Export takes the best of the save and the local services store; each entry says `save` or `local-services`
  (runs uploaded to the patched game's server are marked even when the save also has them). Test export of the
  developer's profile: 222 best times, 113 ghosts (37 from patched play), 584 KB; no profile id in the output.
- Publish: shows what is published and asks for "I agree" (own runs, licence CC0-1.0 or CC-BY-4.0, public and
  lasting; with `--include-others` also responsibility for others' ghosts, which are included by hash only);
  commits under the GitHub noreply address; creates or updates the repository and sets topics. Dry run checked.
- Import refuses while the game runs, validates first (tested: symlinks, path traversal, tampered ghost, wrong
  time, control characters, wrong types, newer format all refused), then merges: riders by hash (named
  opponents are stored under their real id, matched via the hash), better times only, one ghost per rider and
  leaderboard. Tested: new player importing a bundle, re-import (no change), own bundle into own game (nothing
  added), a bundle with 384 opponents into a store that already has them (merged, no duplicates).
- `--include-others-with-names`: like `--include-others`, plus the in-game names the save keeps for some opponents
  (pseudonymous usernames; the publisher decides, and `publish` names them in the agreement text). The local
  server's own placeholders ("Rider <hash>"), which the game may have saved, are never exported as names.
- Publishing always signs now: a key in `~/.ssh` that is on the publisher's GitHub account (authentication or signing
  keys, via the public API) is found automatically; otherwise publish offers to create a signing-only key and add it
  with `gh ssh-key add --type signing` (needs the `admin:ssh_signing_key` scope; gh asks in the browser). The
  signature is verified against GitHub before anything is pushed. The signed manifest carries
  `publisher.statement` (the rider is the publisher's own; `others` came from their game) and the bundle README
  says who published it. Tested: dry run; verification accepts the signing key and rejects others (this Mac's keys
  are not on the developer's GitHub account, so a real publish from here would create the signing key).
- `publish --dry-run` now publishes nothing and leaves the bundle unchanged: it builds the repository exactly as it
  would be pushed (publisher fields, README, signature if a GitHub-registered key exists, the commit under the
  noreply address) as a local git repository `<bundle>-preview` (or `--preview-dir`; only an earlier preview is
  ever replaced), prints the gh commands and a summary. Works without a gh login (placeholder account name).

## 2026-10-10 — Community layer: many bundles, consolidated, incremental

- `scripts/community.py` (list / add / remove / enable / disable / discover / sync / build / install / update /
  status): sources = `community/sources.json` (the author's bundle; the 2019 world records from trialstrackmap,
  pinned commit 9917e5c and file sha256, disabled by default) + the user's own list. `sync` fetches each enabled
  source (bundles: shallow clone, `ghost_bundle.check`, signature against the publisher's GitHub keys; world
  records: two raw files at the pinned commit) into a cache, replacing a cached copy only with one that passes;
  failures keep the last good copy. `build` consolidates from scratch (riders by game hash; claimed own riders:
  signed then earliest wins; best result and fastest ghost per rider and leaderboard; deterministic ids from
  1000000000) into a layer; `install` swaps it into `Documents/LocalServices/community` (game closed).
- Servers (Python and native): overlay the layer at load (installed layer, else one built into the app by
  `build.py --community`), never persist it (`persisted()` restores what it replaced), route its ghosts and
  avatars, skip the player's own rider; the old `--world-records` import is gone and a store's imported world
  records are dropped once (they come from the layer now). Parity test extended (made-up rider with avatar plus all
  downloaded opponents as a layer; legacy world records): PASS, and nothing of the layer in either store.
- `ghost_bundle.py import` removed (replaced by the layer). `ghost_bundle.py update`: re-export with the saved
  options (`.export.json`, excluded from git), summary of changes, publish. Export's `others` now only takes robot
  files the store imported at first start (the original game's downloads): the developer's Documents had 387, of
  which 2 were opponents the local robot module had served, now excluded, so community ghosts are never
  re-published as one's own downloads.
- Developer's PlayCover install: store backed up, `world-records-2019` enabled, layer installed (118 riders, 2158
  results), app rebuilt with the same options (executable unchanged, ca220a37…).
- `ghost_bundle.py update` merges with the bundle's previous content (best result and fastest ghost per
  leaderboard, also for `others`; avatar kept), so updates from different copies of one profile (PlayCover, a
  pulled iPhone/iPad Documents via `--documents`) only add or improve; a different profile is refused and any
  failure restores the bundle. Tested: bundle from the old iPad copy (210 times, 102 ghosts) → update from PlayCover
  (+12 times, +11 ghosts) → update from the iPad copy again (no loss, 222/113); wrong rider refused and restored.
  The update push uses gh's login for that command only (`git -c credential.helper='!gh auth git-credential'`).

## 2026-10-10 — Rider identity without hash collisions; players who were never on Ubisoft

- Never-Ubisoft players already get a 128-bit identity: the server's random version-4 `new_player_profile`. The weak
  spot was the 32-bit game hash used as the merge key (collisions likely at tens of thousands of riders: two
  publishers merged, or a stranger skipped as "me"). Now consolidation keys a bundle's own rider by
  `profile_sha256` (id `uuid5("trials-frontier-rider:" + sha)`), and the hash only links hash-only opponent ghosts,
  and only when unambiguous; both servers recognise the player by sha256 and link a layer rider to a downloaded
  opponent only when the hash is unique in the layer. Parity test: two riders sharing a hash stay apart, the
  player's own bundle is skipped, a stranger with the player's hash shows: PASS.
- Export falls back to the store's `new_player_profile` when the save has no profile id.
- Names: offset 20 (Player+0x10) holds the platform (Ubisoft) name; a player who never logged in has it empty and
  the tutorial nickname in a 24-byte field 148 bytes before the end of the save (found in the offline GTJeffW save;
  empty in jayuph's; same layout, followed by u32 0x285, in all three saves). Servers and export now fall back to
  it. To check in the Trials Fresh playthrough: whether the game copies the login's `nameOnPlatform` ("Rider"
  before a nickname exists) into offset 20.

## 2026-10-10 — Trials Fresh playthrough (new player, never on Ubisoft)

- Played from scratch without gameplay problems: tutorial, races, results and ghost uploads (three new bests, ghosts
  1000–1002), map leaderboards.
- The game stored the server's made-up profile id (b326761d-…) in its save, and the tutorial name ("JBuff") in both
  name fields (offset 20 and the 24-byte field 148 bytes before the end).
- The post-race screen showed "Rider" while the map leaderboards showed "JBuff": the first login of that session
  (before the save existed) answered "Rider" (also sent back by the game as `player_name` in targeting/configuration),
  and the post-race screen uses the login's name, while the map asks `/v1/profiles`, which reads the save. Both
  servers now log the name each login returns (`login as …`) to confirm that a restart logs in as the nickname.
- Also seen (not blocking): `POST playerstats/v1/stats/global_stats` (overall score after each race) is unhandled;
  a player without an avatar gets 404 for their picture and the fallback.
- Why "Rider" then "JBuff" (static analysis): the tutorial's name screen (`MenuzMissionContentLoginName`) stores the
  name as the silent-login name (`OnlineData::setSilentLoginName`, Player+0x6be0 → the field 148 bytes before the
  end of the save); accepting it calls `OnlineCore::activateSilentLogin`, which logs in again (the second login,
  08:44:48). `OnlineAuthenticationMobile::parseTicketData` copies the reply's profileId to Player+0x110 and
  nameOnPlatform to Player+0x10, then overwrites Player+0x10 with the silent-login name if there is one, so the
  server's name only matters before the player has chosen one. Leaderboard entry names come only from
  `/v1/profiles` replies (`OnlineUbiservices::setLeaderBoardInfo`; empty names trigger `resolveLeaderBoardNames`).
  The first race (track 1033, 08:44:04) came before the name existed; the re-login the user asked about is already
  built into the game.
- Correction: "Rider" stayed on the post-race screen for the whole session, not just the first race. Cause: after
  every login of a player with a chosen (silent-login) name, `updateTicketQuery` calls `setName` →
  `ubimobile_changeAccountName`: POST /v2/profiles/sessions, body `{}`, `Authorization: UbiMobile_v1 t=` base64 of
  `account:secret:base64(new name)` (a plain login has two fields); the library keeps the reply's
  `nameOnPlatform` as the account's name. Right after naming, the save on disk did not have the name yet, so the
  server answered "Rider" and the library kept it. Both servers now read the new name from that request, answer
  with it and keep it in the store (`player_name`, which takes priority over the save). Parity test: rename
  adopted and kept, plain logins change nothing: PASS. The existing Trials Fresh profile repairs itself at its next
  login (the game repeats the request every login).
