// Trace mission bookkeeping (activate/solve/reward/cooldown) with mission ids. Logs each distinct
// (function, args, return) once; mutating calls are always logged.
// Usage: frida -p <pid> -q -t 3600 -l frida/trace_missions.js   (stay attached)
const base = Process.mainModule.base.sub(0x100000000);
const ts = () => new Date().toISOString().slice(11, 19);
const seen = new Set();
function hook(addr, name, opts) {
  Interceptor.attach(base.add(addr), {
    onEnter(a) { this.args = opts.args(a); },
    onLeave(r) {
      const line = `${name}(${this.args})${opts.ret ? " -> " + r.toInt32() : ""}`;
      if (opts.always || !seen.has(line)) { seen.add(line); console.log(`${ts()} ${line}`); }
    }
  });
}
const id1 = a => a[1].toUInt32();
const missionRef = a => { try { return a[1].readU32(); } catch (e) { return "?"; } };
const mutating = { always: true };
hook(0x100200998, "PlayerProgress::addMissionActive", { args: id1, ...mutating });
hook(0x1002004a8, "PlayerProgress::removeMissionActive", { args: id1, ...mutating });
hook(0x100200d94, "PlayerProgress::addMissionSolved", { args: a => `${id1(a)}, ${a[2].toInt32() & 1}`, ...mutating });
hook(0x100200e3c, "PlayerProgress::addMissionSolvedInstant", { args: a => `${id1(a)}, ${a[2].toInt32() & 1}`, ...mutating });
hook(0x100200580, "PlayerProgress::removeMissionSolved", { args: id1, ...mutating });
hook(0x100200e84, "PlayerProgress::addRewardCollected", { args: a => `${id1(a)}, ${a[2].toInt32() & 1}`, ...mutating });
hook(0x1002005a8, "PlayerProgress::addMissionAvailable", { args: id1, ...mutating });
hook(0x100200408, "PlayerProgress::removeMissionAvailable", { args: id1, ...mutating });
hook(0x1001fa96c, "MissionSolver::processCompletedMission", { args: missionRef, ...mutating });
hook(0x1001fa750, "MissionSolver::addMissionRewards", { args: a => `mission ${missionRef(a)}, at ${a[2].toInt32()}`, ...mutating });
hook(0x1001f5d20, "MissionManager::activateMissionCooldown", { args: missionRef, ...mutating });
hook(0x1001f3f08, "MissionManager::onActiveMissionOutdated", { args: id1, ...mutating });
hook(0x1001f1ac0, "MissionManager::tryAddAvailableMission", { args: a => { try { return a[2].readU32(); } catch (e) { return "?"; } }, ret: true });
hook(0x1001f420c, "MissionManager::hasMissionEnded", { args: id1, ret: true });
hook(0x1001f47cc, "MissionManager::isMissionInCooldown", { args: id1, ret: true });
hook(0x100200c4c, "PlayerProgress::isRewardCollected", { args: id1, ret: true });
console.log("mission tracer attached");
