"""Read and minimally rewrite Trials Frontier datapacks (.dat), e.g. data/TrialsMobile/content.dat.

Layout (datapack::DataPack): u32 magic, u32 count, u32 entry_size (12); count x entry {u32 unpacked_size,
u32 offset, u32 name_hash}; the data area starts at 12 + count * 12 and offsets are relative to it. Each file:
u32 stored_size, u8 compression (1 = zlib, 0 = raw), 3 bytes (de c0 de), then the stored bytes.

replace_file() appends the new file at the end and repoints only its own entry, so every other byte of the pack is
unchanged (deterministic for a given input).
"""
import re
import struct
import zlib


def game_hash(s):
    """mt::String::getHashCode, used for datapack file names."""
    b = s.encode()
    n, x = len(b), 0
    for c in b:
        c = c - 256 if c > 127 else c
        x = (x + n * c) & 0xFFFFFFFF
        n = ((n & 0xFFFF) * 18000 + (n >> 16)) & 0xFFFFFFFF
    return x


def _index(pack):
    magic, count, esize = struct.unpack_from("<3I", pack, 0)
    if esize != 12:
        raise ValueError("unexpected datapack entry size %d" % esize)
    return 12 + count * esize, [(12 + i * esize,) + struct.unpack_from("<3I", pack, 12 + i * esize) for i in range(count)]


def read_file(pack, name_hash):
    base, entries = _index(pack)
    for _, size, off, h in entries:
        if h == name_hash:
            stored, comp = struct.unpack_from("<IB", pack, base + off)
            body = pack[base + off + 8:base + off + 8 + stored]
            return zlib.decompress(body) if comp == 1 else body
    raise KeyError("%08x not in pack" % name_hash)


def replace_file(pack, name_hash, body):
    base, entries = _index(pack)
    for pos, _, off, h in entries:
        if h == name_hash:
            _, comp, *tag = struct.unpack_from("<IBBBB", pack, base + off)
            stored = zlib.compress(body, 9) if comp == 1 else body
            new_off = len(pack) - base
            out = bytearray(pack) + struct.pack("<IBBBB", len(stored), comp, *tag) + stored
            struct.pack_into("<2I", out, pos, len(body), new_off)
            return bytes(out)
    raise KeyError("%08x not in pack" % name_hash)


def store_item_price(text, item_id, price_hard):
    """Turn an App Store item of a store config (JSON with CRLF) into a gem-priced in-game item: empty its "ID"
    (no IAP product) and set the first "PH" of its "P" price list. The item must occur exactly once."""
    anchor = '"ID": "%s"' % item_id
    if text.count(anchor) != 1:
        raise ValueError("%s found %d times" % (item_id, text.count(anchor)))
    start = text.index(anchor)
    end = text.find('"FTS"', start)
    block = text[start:end]
    new_block, n = re.subn(r'"PH":\s*0\b', '"PH": %d' % price_hard, block.replace(anchor, '"ID": ""', 1), count=1)
    if n != 1:
        raise ValueError("no zero hard price in %s" % item_id)
    return text[:start] + new_block + text[end:]


def level_position(text, level_id, x, y, from_x=-10000, from_y=-10000):
    """Move a level in /conf/levels.txt on the map: the level object with "ID":level_id must currently be at
    (from_x, from_y) — by default parked at (-10000, -10000), outside LevelMetaData::isAvailableOnMap's circle."""
    m = list(re.finditer(r'\{[^{}]*"ID":\s*%d\s*,[^{}]*\}' % level_id, text))
    if len(m) != 1:
        raise ValueError("level %d found %d times" % (level_id, len(m)))
    obj = m[0].group(0)
    new, n = re.subn(r'"X":\s*%d\s*,(\s*)"Y":\s*%d(?!\d)' % (from_x, from_y), '"X":%d,\\1"Y":%d' % (x, y), obj)
    if n != 1:
        raise ValueError("level %d is not at (%d, %d)" % (level_id, from_x, from_y))
    return text[:m[0].start()] + new + text[m[0].end():]


def level_bike_tier(text, level_id, old, new):
    """Change a level's bike tier "B" in /conf/levels.txt (must currently be `old`)."""
    m = list(re.finditer(r'\{[^{}]*"ID":\s*%d\s*,[^{}]*\}' % level_id, text))
    if len(m) != 1:
        raise ValueError("level %d found %d times" % (level_id, len(m)))
    obj, n = re.subn(r'"B":\s*%d\s*,' % old, '"B":%d,' % new, m[0].group(0))
    if n != 1:
        raise ValueError("level %d has no bike tier %d" % (level_id, old))
    return text[:m[0].start()] + obj + text[m[0].end():]


def add_strings(data, strings):
    """Append (key, text) entries to a /gen/lang/<language>_strings.bin table: 'LOCF', u8 version, u32 count, then
    count x {u32 getHashCode(key), u16 length incl. NUL, text}. Keys must not exist yet."""
    if data[:4] != b"LOCF":
        raise ValueError("not a LOCF string table")
    count = struct.unpack_from("<I", data, 5)[0]
    i, keys = 9, set()
    for _ in range(count):
        k, ln = struct.unpack_from("<IH", data, i)
        keys.add(k)
        i += 6 + ln
    if i != len(data):
        raise ValueError("unexpected string table layout")
    out = bytearray(data)
    for key, text in strings:
        h = game_hash(key)
        if h in keys:
            raise ValueError("string %r already present" % key)
        raw = text.encode("utf-8") + b"\0"
        out += struct.pack("<IH", h, len(raw)) + raw
    struct.pack_into("<I", out, 5, count + len(strings))
    return bytes(out)


def apply_content_patch(pack, patch):
    """Apply one spec "content_patches" entry to the pack bytes; returns the new pack bytes."""
    h = game_hash(patch["file"])
    if patch.get("binary"):
        data = read_file(pack, h)
        for edit in patch["edits"]:
            if edit["op"] == "add_strings":
                data = add_strings(data, [(s["key"], s["text"]) for s in edit["strings"]])
            else:
                raise ValueError("unknown binary content edit %r" % edit["op"])
        return replace_file(pack, h, data)
    text = read_file(pack, h).decode("utf-8")
    for edit in patch["edits"]:
        if edit["op"] == "store_item_price":
            text = store_item_price(text, edit["item_id"], edit["price_hard"])
        elif edit["op"] == "level_position":
            text = level_position(text, edit["level_id"], edit["x"], edit["y"],
                                  edit.get("from_x", -10000), edit.get("from_y", -10000))
        elif edit["op"] == "level_bike_tier":
            text = level_bike_tier(text, edit["level_id"], edit["old"], edit["new"])
        else:
            raise ValueError("unknown content edit %r" % edit["op"])
    return replace_file(pack, h, text.encode("utf-8"))
