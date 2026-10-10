"""Read and minimally rewrite Trials Frontier datapacks (.dat), e.g. data/TrialsMobile/content.dat.

Layout (datapack::DataPack): u32 magic, u32 count, u32 entry_size (12); count x entry {u32 unpacked_size,
u32 offset, u32 name_hash}; the data area starts at 12 + count * 12 and offsets are relative to it. Each file:
u32 stored_size, u8 compression (1 = zlib, 0 = raw), 3 bytes (de c0 de), then the stored bytes.

replace_file() appends the new file at the end and repoints only its own entry, so every other byte of the pack is
unchanged (deterministic for a given input).

Texture packs (TrialsTexturesDL*.dat) have entry_size 24: {u32 unpacked_size, u32 offset, u32 width << 16 | height,
u32 format, u32 name_hash, u32 0x20}, same file layout; the 128x128 menu icons are plain RGBA8888 (straight alpha).
add_texture() appends one entry and its file; offsets are relative to the data area, so nothing else moves.
"""
import math
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


def _texture_index(pack):
    magic, count, esize = struct.unpack_from("<3I", pack, 0)
    if esize != 24:
        raise ValueError("not a texture pack (entry size %d)" % esize)
    return 12 + count * 24, [(12 + i * 24,) + struct.unpack_from("<6I", pack, 12 + i * 24) for i in range(count)]


def read_texture(pack, name_hash):
    """(width, height, format, pixels) of a texture in a texture pack."""
    base, entries = _texture_index(pack)
    for _, size, off, dims, fmt, h, _ in entries:
        if h == name_hash:
            stored, comp = struct.unpack_from("<IB", pack, base + off)
            body = pack[base + off + 8:base + off + 8 + stored]
            return dims >> 16, dims & 0xFFFF, fmt, zlib.decompress(body) if comp == 1 else body
    raise KeyError("texture %08x not in pack" % name_hash)


def add_texture(pack, name_hash, width, height, fmt, pixels):
    """Append a texture (zlib-compressed, entry and file header copied from the pack's first entry's layout)."""
    base, entries = _texture_index(pack)
    if any(e[5] == name_hash for e in entries):
        raise ValueError("texture %08x already in pack" % name_hash)
    tag = pack[base + entries[0][2] + 5:base + entries[0][2] + 8]
    stored = zlib.compress(pixels, 9)
    entry = struct.pack("<6I", len(pixels), len(pack) - base, width << 16 | height, fmt, name_hash, entries[0][6])
    out = bytearray(pack[:base]) + entry + pack[base:] + struct.pack("<IB", len(stored), 1) + tag + stored
    struct.pack_into("<I", out, 4, len(entries) + 1)
    return bytes(out)


def event_tab_icon(disc, art, size, scale):
    """A round event-tab icon: `disc` (an existing tab icon, RGBA size x size) with its coloured artwork removed —
    pixels with saturation, grown by 2 px, repainted with the median uncoloured pixel at the same distance from the
    centre, so its own rim, gloss and shadow stay — and `art` (RGBA size x size) scaled by `scale` on top."""
    px = lambda b, x, y: tuple(b[(y * size + x) * 4:(y * size + x) * 4 + 4])
    c = (size - 1) / 2
    mask = {(x, y) for y in range(size) for x in range(size)
            if px(disc, x, y)[3] and max(px(disc, x, y)[:3]) - min(px(disc, x, y)[:3]) > 30}
    for _ in range(2):
        mask |= {(x + dx, y + dy) for x, y in mask for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    rings = {}
    for y in range(size):
        for x in range(size):
            if (x, y) not in mask:
                rings.setdefault(round(math.hypot(x - c, y - c)), []).append(px(disc, x, y))
    med = {r: sorted(v, key=lambda p: (sum(p[:3]), p))[len(v) // 2] for r, v in rings.items()}
    ring = lambda r: med[min(med, key=lambda k: (abs(k - r), k))]
    img = [list(ring(round(math.hypot(x - c, y - c))) if (x, y) in mask else px(disc, x, y))
           for y in range(size) for x in range(size)]

    def sample(fx, fy):   # bilinear, premultiplied alpha
        x0, y0 = math.floor(fx), math.floor(fy)
        ax, ay = fx - x0, fy - y0
        acc = [0.0] * 4
        for dx, dy, w in ((0, 0, (1 - ax) * (1 - ay)), (1, 0, ax * (1 - ay)), (0, 1, (1 - ax) * ay), (1, 1, ax * ay)):
            if 0 <= x0 + dx < size and 0 <= y0 + dy < size:
                r, g, b, a = px(art, x0 + dx, y0 + dy)
                a /= 255
                acc = [acc[0] + r * a * w, acc[1] + g * a * w, acc[2] + b * a * w, acc[3] + a * w]
        return acc
    for y in range(size):
        for x in range(size):
            r, g, b, a = sample((x - c) / scale + c, (y - c) / scale + c + 2)
            if a <= 0:
                continue
            p = img[y * size + x]
            da = p[3] / 255
            oa = a + da * (1 - a)
            p[:3] = [round((s + q * da * (1 - a)) / oa) for s, q in zip((r, g, b), p[:3])]
            p[3] = round(oa * 255)
    return bytes(min(255, max(0, v)) for p in img for v in p)


def override_custom_param(text, mission, override_type, key, value):
    """Mission file: add `key=value` to the quoted custom data of the mission's (single) override of the given
    type, e.g. `o,13,...,"2629429319='447'",0` -> `o,13,...,"2629429319='447',<key>=<value>",0`."""
    out, current, done = [], None, 0
    for line in text.split("\n"):
        m = re.match(r"^(\d+),", line)
        if m and not line.startswith(("u,", "o,", "t,", "r,", "a,", "b,", "c,", "m,", "z,")):
            current = int(m.group(1))
        if current == mission and line.startswith("o,%d," % override_type):
            q = re.match(r'^(o,(?:[^,"]*,){8}")([^"]*)(".*)$', line, re.S)
            if not q:
                raise ValueError("mission %d: unexpected override line %r" % (mission, line[:60]))
            if re.search(r"(^|,)%d=" % key, q.group(2)):
                raise ValueError("mission %d: key %d already set" % (mission, key))
            line = q.group(1) + (q.group(2) + "," if q.group(2) else "") + "%d=%d" % (key, value) + q.group(3)
            done += 1
        out.append(line)
    if done != 1:
        raise ValueError("mission %d has %d overrides of type %d" % (mission, done, override_type))
    return "\n".join(out)


def replace_mission_line(text, mission, old, new):
    """Mission file: replace one line of a mission's block (exact match without the line end, exactly once), e.g.
    an unlock condition `u,3,10,22,1` -> `u,3,0,22,1`."""
    out, current, done = [], None, 0
    for line in text.split("\n"):
        m = re.match(r"^(\d+),", line)
        if m and not line.startswith(("u,", "o,", "t,", "r,", "a,", "b,", "c,", "m,", "z,")):
            current = int(m.group(1))
        body = line.rstrip("\r")
        if current == mission and body == old:
            line = new + line[len(body):]
            done += 1
        out.append(line)
    if done != 1:
        raise ValueError("mission %d: %r found %d times" % (mission, old, done))
    return "\n".join(out)


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


def shift_mission_dates(text, missions, delta):
    """Mission file (content 0xc4125fdb): move the dated parts of the listed missions by delta seconds. Unlock
    windows `u,6,<f>,<start>,<end>` (0 stays 0: open-ended) and notification times `o,16,0,0,0,<time>,...`."""
    out, current = [], None
    for line in text.split("\n"):
        m = re.match(r"^(\d+),", line)
        if m and not line.startswith(("u,", "o,", "t,", "r,", "a,", "b,", "c,", "m,", "z,")):
            current = int(m.group(1))
        if current in missions:
            u = re.match(r"^u,6,(\d+),(\d+),(\d+)(\r?)$", line)
            n = re.match(r"^(o,16,0,0,0,)(\d+)(,.*)$", line, re.S)
            if u:
                a, b = int(u.group(2)), int(u.group(3))
                line = f"u,6,{u.group(1)},{a + delta if a else 0},{b + delta if b else 0}{u.group(4)}"
            elif n and int(n.group(2)) > 1_000_000_000:
                line = f"{n.group(1)}{int(n.group(2)) + delta}{n.group(3)}"
        out.append(line)
    return "\n".join(out)


def apply_content_patch(pack, patch):
    """Apply one spec "content_patches" entry to the pack bytes; returns the new pack bytes."""
    if patch.get("textures"):
        for edit in patch["edits"]:
            if edit["op"] == "event_tab_icon":
                w, h, fmt, disc = read_texture(pack, int(edit["disc"], 16))
                aw, ah, _, art = read_texture(pack, int(edit["art"], 16))
                if (w, h) != (aw, ah) or len(disc) != w * h * 4 or len(art) != w * h * 4 or w != h:
                    raise ValueError("event_tab_icon needs two square RGBA textures of the same size")
                pack = add_texture(pack, game_hash(edit["name"]), w, h, fmt, event_tab_icon(disc, art, w, edit["scale"]))
            else:
                raise ValueError("unknown texture edit %r" % edit["op"])
        return pack
    h = int(patch["file_hash"], 16) if patch.get("file_hash") else game_hash(patch["file"])
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
        elif edit["op"] == "shift_mission_dates":
            text = shift_mission_dates(text, set(edit["missions"]), int(edit["to"]) - int(edit["from"]))
        elif edit["op"] == "level_bike_tier":
            text = level_bike_tier(text, edit["level_id"], edit["old"], edit["new"])
        elif edit["op"] == "replace_mission_line":
            text = replace_mission_line(text, edit["mission"], edit["old"], edit["new"])
        elif edit["op"] == "override_custom_param":
            # value_texture: a texture name, stored as its signed hash (the game parses the value as an int)
            v = edit["value"] if "value" in edit else game_hash(edit["value_texture"])
            text = override_custom_param(text, edit["mission"], edit["override"], game_hash(edit["key"]),
                                         v - (1 << 32) if v >= 1 << 31 else v)
        else:
            raise ValueError("unknown content edit %r" % edit["op"])
    return replace_file(pack, h, text.encode("utf-8"))
