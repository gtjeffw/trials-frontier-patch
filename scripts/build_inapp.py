"""Build the native local services (inapp/): the in-app library and/or the macOS test tool.

Usage: python3 -I build_inapp.py <out dir> [--target dylib|cli|all]

  dylib: libTFLocalServices.dylib for the game (arm64, iOS 15+; runs under PlayCover too), loaded through an
         LC_LOAD_DYLIB "@executable_path/Frameworks/libTFLocalServices.dylib" (see the local-services group).
  cli:   tfserver for macOS, the same services as a command-line program (tests, development).
Uses Xcode's clang (xcrun); plain C/Objective-C with ARC, Foundation, CommonCrypto and zlib only.
"""
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "inapp")
CORE = ["src/TFSave.m", "src/TFHTTP.m", "src/TFServices.m", "src/TFLocalServices.m"]
FLAGS = ["-fobjc-arc", "-O2", "-Wall", "-Wno-deprecated-declarations", "-fno-common", "-I", os.path.join(ROOT, "src"),
         "-framework", "Foundation", "-lz"]


def clang(sdk, args):
    cmd = ["xcrun", "--sdk", sdk, "clang"] + args
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    out = os.path.abspath(sys.argv[1])
    target = sys.argv[sys.argv.index("--target") + 1] if "--target" in sys.argv else "all"
    os.makedirs(out, exist_ok=True)
    if target in ("cli", "all"):
        clang("macosx", ["-arch", "arm64", "-mmacosx-version-min=12.0"] + FLAGS + CORE + ["cli/tfserver.m",
              "-o", os.path.join(out, "tfserver")])
    if target in ("dylib", "all"):
        clang("iphoneos", ["-target", "arm64-apple-ios15.0", "-dynamiclib"] + FLAGS + CORE + ["src/TFEntry.m",
              "-install_name", "@executable_path/Frameworks/libTFLocalServices.dylib",
              "-o", os.path.join(out, "libTFLocalServices.dylib")])


if __name__ == "__main__":
    main()
