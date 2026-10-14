"""Decode a Trials Frontier save file (player.bin) into its raw, decompressed form.

Usage: python3 -I decode_save.py <player.bin> <out.raw>
       (encode() writes a save back: header checksum = SaveFile::fletcher32, keyed with the Protection's a and b)

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


CHECK_SEED, CHECK_MULT = 0xEC51ED, 0x24D7  # the other two Protection values: the checksum's key stream


def fletcher32(data, seed=CHECK_SEED, mult=CHECK_MULT):
    """mt::file::SaveFile::fletcher32 over the uncompressed data: Fletcher-32 sums starting at 0xffff, each byte first
    keyed by a stream (k + k*byte, low byte; k *= mult), folded every 359 bytes."""
    n, i, k = len(data), 0, seed
    if n == 0:
        return 0xFFFFFFFF
    s1 = s2 = 0xFFFF
    while n:
        block = min(n, 359)
        n -= block
        for x in data[i:i + block]:
            s1 = (s1 + ((k + k * x) & 0xFF)) & 0xFFFFFFFF
            s2 = (s2 + s1) & 0xFFFFFFFF
            k = (k * mult) & 0xFFFFFFFF
        i += block
        s1 = (s1 >> 16) + (s1 & 0xFFFF)
        s2 = (s2 >> 16) + (s2 & 0xFFFF)
    return ((s2 * 0x10001) & 0xFFFF0000) | (((s1 >> 16) + (s1 & 0xFFFF)) & 0xFFFF)


def encode(body, version=114):
    """The inverse of decode: what the game writes (header with checksum and size, zlib level 9, scrambled).
    Rebuilds real saves byte for byte."""
    return unscramble(struct.pack("<4I", version, fletcher32(body), len(body), 0) + zlib.compress(body, 9))


if __name__ == "__main__":
    header, body = decode(open(sys.argv[1], "rb").read())
    print(f"version={header['version']} checksum=0x{header['checksum']:08x} size={header['size']} -> {len(body)} bytes")
    if len(sys.argv) > 2:
        open(sys.argv[2], "wb").write(body)
        print(f"wrote {sys.argv[2]}")
