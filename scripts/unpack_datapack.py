"""Unpack a Trials Frontier datapack (.dat) into files named by their name hash.

Usage: python3 -I unpack_datapack.py <pack.dat> <out_dir>

Layout (from datapack::DataPack::readHeader / loadFile / fillBuffer):
  u32 magic, u32 count, u32 entry_size (12)
  count x entry: u32 a, u32 b, u32 name_hash        (one of a/b is the data offset, see below)
  data area starts at 12 + count * entry_size; each file = FileHeader + payload
  FileHeader: u32 stored_size, u8 compression (1 = zlib, 0 = raw), u8, u8, u8
"""
import os
import struct
import sys
import zlib

path, out = sys.argv[1], sys.argv[2]
data = open(path, "rb").read()
magic, count, esize = struct.unpack_from("<3I", data, 0)
base = 12 + count * esize
entries = [struct.unpack_from("<3I", data, 12 + i * esize) for i in range(count)]


def header_ok(off):
    if base + off + 8 > len(data):
        return False
    size, comp = struct.unpack_from("<IB", data, base + off)
    return comp in (0, 1) and base + off + 8 + size <= len(data)


# work out which field is the offset by checking which one points at valid file headers
offset_field = max((0, 1), key=lambda k: sum(header_ok(e[k]) for e in entries))
os.makedirs(out, exist_ok=True)
ok = bad = 0
for a_b_hash in entries:
    off, name_hash = a_b_hash[offset_field], a_b_hash[2]
    size, comp = struct.unpack_from("<IB", data, base + off)
    payload = data[base + off + 8: base + off + 8 + size]
    try:
        body = zlib.decompress(payload) if comp == 1 else payload
        ok += 1
    except zlib.error:
        body, bad = payload, bad + 1
    open(os.path.join(out, f"{name_hash:08x}.bin"), "wb").write(body)
print(f"{os.path.basename(path)}: magic=0x{magic:08x} files={count} offset_field={offset_field} ok={ok} failed={bad}")
