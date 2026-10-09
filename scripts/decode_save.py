"""Decode a Trials Frontier save file (player.bin) into its raw, decompressed form.

Usage: python3 -I decode_save.py <player.bin> <out.raw>

Derived from TrialsFrontier 7.9.0 (iOS):
  tr::Player::load() -> mt::file::SaveFile(Protection @ 0x100af1ff0) -> SaveFile::open / processHeader
  Protection = u32 seed, u32 mult, u32 a, u32 b  (+ u8 compress flag, 0 for player.bin)
  1. XOR every byte with the low byte of `key`, then key = key * mult (32-bit), starting at key = seed.
  2. Header: u32 version, u32 checksum, u32 uncompressed_size, u32 reserved.
  3. If uncompressed_size != 0, the remaining bytes are zlib.
"""
import struct
import sys
import zlib

SEED, MULT = 0x9D, 0x20B9


def unscramble(data, seed=SEED, mult=MULT):
    out = bytearray(data)
    key = seed
    for i in range(len(out)):
        out[i] ^= key & 0xFF
        key = (key * mult) & 0xFFFFFFFF
    return bytes(out)


def decode(data):
    plain = unscramble(data)
    version, checksum, size, reserved = struct.unpack_from("<4I", plain)
    body = zlib.decompress(plain[16:]) if size else plain[16:]
    return {"version": version, "checksum": checksum, "size": size, "reserved": reserved}, body


if __name__ == "__main__":
    header, body = decode(open(sys.argv[1], "rb").read())
    print(f"version={header['version']} checksum=0x{header['checksum']:08x} size={header['size']} -> {len(body)} bytes")
    if len(sys.argv) > 2:
        open(sys.argv[2], "wb").write(body)
        print(f"wrote {sys.argv[2]}")
