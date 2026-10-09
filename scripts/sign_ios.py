"""Sign a patched Trials Frontier .ipa for an iPhone/iPad with your own (free) Apple development account.

Usage: python3 -I sign_ios.py <patched.ipa> <out dir> [--profile <file.mobileprovision>] [--identity "<name or hash>"]

Prerequisite (once): in Xcode, sign in with your Apple ID (Settings > Accounts), then create any iOS app project
with the bundle id you built the game with (build.py --bundle-id), choose your Personal Team, connect the device and
run it once: Xcode creates the "Apple Development" certificate and a provisioning profile for that bundle id.

The script finds that profile (by the app's CFBundleIdentifier, newest first) in
~/Library/Developer/Xcode/UserData/Provisioning Profiles (or uses --profile), takes the signing identity whose
certificate is in the profile, writes entitlements from the profile (application-identifier, team, get-task-allow,
keychain-access-groups), embeds the profile, signs Frameworks/*.dylib and then the app, and writes
<out dir>/TrialsFrontier.app (for `xcrun devicectl device install app`) and a signed .ipa.
Free accounts: the signature expires after 7 days; re-run this script and reinstall (the game's data stays).
"""
import glob
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


def decode_profile(path):
    raw = subprocess.run(["security", "cms", "-D", "-i", path], capture_output=True, check=True).stdout
    return plistlib.loads(raw)


def find_profile(bundle_id):
    dirs = [os.path.expanduser("~/Library/Developer/Xcode/UserData/Provisioning Profiles"),
            os.path.expanduser("~/Library/MobileDevice/Provisioning Profiles")]
    found = []
    for d in dirs:
        for p in glob.glob(os.path.join(d, "*.mobileprovision")):
            try:
                prof = decode_profile(p)
            except subprocess.CalledProcessError:
                continue
            app_id = prof["Entitlements"].get("application-identifier", "")
            team = prof["TeamIdentifier"][0]
            if app_id in (f"{team}.{bundle_id}", f"{team}.*"):
                found.append((app_id.endswith("*"), -prof["CreationDate"].timestamp(), p, prof))
    if not found:
        sys.exit(f"no provisioning profile for {bundle_id}: create one in Xcode first (see the usage notes)")
    return sorted(found)[0][2:]


def identity_for(prof, wanted):
    out = subprocess.run(["security", "find-identity", "-v", "-p", "codesigning"], capture_output=True, text=True).stdout
    certs = {hashlib.sha1(c).hexdigest().upper() for c in prof["DeveloperCertificates"]}
    for line in out.splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[1] in certs and (not wanted or wanted in line):
            return parts[1], parts[2].strip('"')
    sys.exit("no signing identity in the keychain matches the profile's certificates (open Xcode > Settings > Accounts)")


def main():
    profile_path, wanted = opt("--profile"), opt("--identity")
    ipa, out = sys.argv[1:3]
    work = tempfile.mkdtemp(prefix="tf-sign-")
    try:
        zipfile.ZipFile(ipa).extractall(work)
        apps = glob.glob(os.path.join(work, "Payload", "*.app"))
        app = apps[0]
        info = plistlib.load(open(os.path.join(app, "Info.plist"), "rb"))
        bundle_id = info["CFBundleIdentifier"]
        if profile_path:
            prof = decode_profile(profile_path)
        else:
            profile_path, prof = find_profile(bundle_id)
        team = prof["TeamIdentifier"][0]
        sha1, name = identity_for(prof, wanted)
        ents = dict(prof["Entitlements"])
        ents["application-identifier"] = f"{team}.{bundle_id}"
        if "keychain-access-groups" in ents:
            ents["keychain-access-groups"] = [f"{team}.{bundle_id}" if g.endswith("*") else g for g in ents["keychain-access-groups"]]
        ent_path = os.path.join(work, "entitlements.plist")
        plistlib.dump(ents, open(ent_path, "wb"))
        shutil.rmtree(os.path.join(app, "_CodeSignature"), ignore_errors=True)
        for leftover in ("TrialsFrontier_dev.entitlements",):
            p = os.path.join(app, leftover)
            if os.path.exists(p):
                os.remove(p)
        shutil.copy(profile_path, os.path.join(app, "embedded.mobileprovision"))
        print(f"signing {bundle_id} with {name} (team {team}), profile {os.path.basename(profile_path)}, "
              f"expires {prof['ExpirationDate']:%Y-%m-%d}")
        for lib in sorted(glob.glob(os.path.join(app, "Frameworks", "*.dylib"))):
            subprocess.run(["codesign", "-f", "-s", sha1, "--timestamp=none", lib], check=True)
        subprocess.run(["codesign", "-f", "-s", sha1, "--timestamp=none", "--entitlements", ent_path, app], check=True)
        subprocess.run(["codesign", "--verify", "--deep", "--strict", app], check=True)
        os.makedirs(out, exist_ok=True)
        dest = os.path.join(out, os.path.basename(app))
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(app, dest, symlinks=True)
        signed = os.path.join(out, os.path.splitext(os.path.basename(ipa))[0] + "-signed.ipa")
        shutil.make_archive(signed[:-4], "zip", work, "Payload")
        os.replace(signed[:-4] + ".zip", signed)
        print(f"wrote {dest} and {signed}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
