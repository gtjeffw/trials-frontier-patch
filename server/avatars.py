"""Generated rider avatars for riders without a picture: a pixel-art motocross helmet (146x146 PNG) whose shape,
colours and pattern come from the sha256 of the rider's id: visor or none, squint or round goggles, full or open face
(with the rider's profile in one of five skin tones), 16 shell and 12 accent colours, 6 lens tints, 8 backgrounds,
12 patterns (plain, stripe, twin stripes, two-tone, diagonals, checkers, dots, chevrons, flames, bolt, stars, race
number).

Deterministic and dependency-free, so the in-app server (inapp/src/TFAvatar.m) produces byte-identical PNGs:
integer maths only (floor division as in Python), colours from fixed palettes, an indexed-colour PNG whose zlib
stream uses stored (uncompressed) blocks, so no compressor is involved. tests/test_parity.py compares the two.
"""
import hashlib
import struct
import zlib

SIZE, GRID = 146, 32
CELL = SIZE // GRID                 # 4 px per grid cell
PAD = (SIZE - CELL * GRID) // 2     # 9 px border

# Base drawing (visor, squint goggles, full face), side view facing right: . background, O outline, S shell,
# H shine, P peak, p peak outline, g goggle frame/strap, G goggle lens, C chin guard, V vent, c chin outline,
# K inner line, L neck trim. Variants remove the peak (P p) or the chin guard (C V c), or stamp round goggles;
# the outline is then redrawn where shell meets background.
HELMET = [
    "................................",
    "............OOOOOOOO............",
    ".........OOOSSSSSSSSOOO.........",
    ".......OOSSSHHSSSSSSSSSOO.......",
    "......OSSSHHSSSSSSSSSSSSSO......",
    ".....OSSSHSSSSSSSSSSSSSSSSO.....",
    "....OSSSSSSSSSSSSSSSSSSSSSSOppp.",
    "....OSSSSSSSSSSSSSSSSSSSSSSPPPPp",
    "...OSSSSSSSSSSSSSSSSSSSSSSSOPPPp",
    "...OSSSSSSSSSSSSSSSSSSSSSSSSOppp",
    "...OSSSSSSSSSSSSSSSSSSSSSSSSO...",
    "..OSSSSSSSSSSSSSSSSSSSSSSSSSSO..",
    "..OSSSSSSSSSSSSSSSSSggggggggCO..",
    "..OggggggggggggggggggGGGGGGgCCc.",
    "..OSSSSSSSSSSSSSSSSSgGGGGGGgCCCc",
    "..OSSSSSSSSSSSSSSSSSgGGGGGGgCCCc",
    "..OSSSSSSSSSSSSSSSSSggggggggCCCc",
    "..OSSSSSSSSSSSSSSSSSSSSKCCCCCCCc",
    "..OSSSSSSSSSSSSSSSSSSSSCCCCCCCCc",
    "..OSSSSSSSSSSSSSSSSSSSCCVCCVCCCc",
    "...OSSSSSSSSSSSSSSSSSSCCCCCCCCCc",
    "...OSSSSSSSSSSSSSSSSSCCVCCVCCCCc",
    "....OSSSSSSSSSSSSSSSSCCCCCCCCCCc",
    ".....OSSSSSSSSSSSSSSCCCCCCCCCCc.",
    "......OSSSSSSSSSSSSCCCCCCCCCCc..",
    ".......OLLLLLLLLLLLCCCCCCCCCc...",
    "........OOOOOOOOOOOcccccccccc...",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
]


def _round_goggles():
    """A round goggle (frame g, lens H/G) centred at (23.5, 13.5), integer maths: radius 4 frame, radius 3 lens."""
    out = {}
    for y in range(9, 19):
        for x in range(19, 29):
            r2 = (2 * x - 47) ** 2 + (2 * y - 27) ** 2
            if r2 <= 36:
                out[(x, y)] = "H" if (x, y) == (22, 12) else "G"
            elif r2 <= 64:
                out[(x, y)] = "g"
    return out


ROUND_GOGGLES = _round_goggles()
# Open face: the rider's profile where the chin guard was (F skin, f skin shadow, m mouth)
FACE = {
    **{(x, y): "F" for y in (12, 13, 14) for x in (28, 29)},   # brow
    **{(x, y): "F" for y in (15, 16) for x in (28, 29, 30)},   # nose
    **{(x, 17): "F" for x in range(20, 31)},
    **{(x, 18): "F" for x in range(20, 30)},
    **{(x, 19): "F" for x in range(20, 29)},
    **{(x, 20): "F" for x in range(20, 27)}, (27, 20): "m", (28, 20): "m",
    **{(x, y): "F" for y in (21, 22) for x in range(20, 29)},   # jaw
    **{(x, 23): "F" for x in range(20, 28)},
    **{(x, 24): "F" for x in range(19, 26)}, (26, 24): "O",   # jaw sloping into the helmet's lower edge
    **{(x, 25): "f" for x in range(19, 25)}, (25, 25): "O",   # under the jaw
    **{(x, 26): "O" for x in range(19, 26)},                  # the bottom outline continues under the jaw
}


def _shape(peak, round_goggles, full_face):
    grid = [list(row) for row in HELMET]
    for y, row in enumerate(grid):
        for x, c in enumerate(row):
            if (not peak and c in "Pp") or (not full_face and c in "CVcK"):
                row[x] = "."
    if not peak:
        grid[7][27] = "S"            # close the dome where the peak was
    if round_goggles:
        for y in range(12, 17):
            for x in range(20, 28):
                if grid[y][x] in "gG" and not (y == 13 and x < 20):
                    grid[y][x] = "S"
        for (x, y), c in ROUND_GOGGLES.items():
            grid[y][x] = c
    if not full_face:
        for (x, y), c in FACE.items():
            if grid[y][x] not in "gGH":
                grid[y][x] = c
        for y, row in enumerate(grid):   # a dark line where the helmet meets the face
            for x, c in enumerate(row):
                if c == "S" and any(0 <= y + dy < GRID and 0 <= x + dx < GRID and grid[y + dy][x + dx] in "Ffm"
                                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    row[x] = "K"
    for y, row in enumerate(grid):   # outline where shell now meets the background
        for x, c in enumerate(row):
            if c in "SHLCKF" and any(not (0 <= y + dy < GRID and 0 <= x + dx < GRID) or grid[y + dy][x + dx] == "."
                                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                row[x] = "O"
    return ["".join(r) for r in grid]


SHELLS = [(214, 40, 40), (232, 112, 22), (240, 196, 25), (124, 186, 36), (32, 150, 72), (24, 160, 150),
          (30, 120, 210), (40, 64, 170), (120, 60, 200), (190, 50, 160), (236, 236, 236), (40, 40, 46),
          (150, 150, 158), (120, 76, 40), (250, 120, 150), (0, 190, 220)]
ACCENTS = [(255, 255, 255), (20, 20, 24), (255, 210, 0), (255, 90, 0), (0, 200, 255), (230, 30, 60),
           (60, 220, 90), (160, 90, 255), (255, 120, 200), (200, 200, 210), (0, 120, 255), (255, 160, 40)]
LENSES = [(60, 70, 90), (40, 140, 230), (235, 175, 30), (220, 60, 50), (60, 200, 140), (180, 110, 230)]
BACKGROUNDS = [(236, 230, 216), (214, 228, 238), (226, 238, 214), (240, 222, 222), (230, 222, 240),
               (244, 236, 206), (214, 236, 232), (226, 226, 230)]
OUTLINE, FRAME, VENT, TRIM, PLATE, DIGIT = (26, 26, 30), (34, 34, 40), (20, 20, 24), (60, 60, 66), (250, 250, 245), (20, 20, 24)
SHINE = (255, 255, 255)
SKINS = [((255, 214, 178), (214, 160, 120)), ((236, 188, 140), (190, 136, 92)), ((198, 140, 96), (150, 98, 62)),
         ((150, 98, 64), (104, 64, 40)), ((104, 66, 44), (70, 42, 28))]
MOUTH = (120, 40, 40)

# 3x5 digits for the race-number plate
DIGITS = ["111101101101111", "010110010010111", "111001111100111", "111001111001111", "101101111001001",
          "111100111001111", "111100111101111", "111001010100100", "111101111101111", "111101111001111"]
BOLT = [(15, 4), (14, 5), (13, 6), (12, 7), (11, 8), (12, 8), (13, 8), (14, 8), (13, 9), (12, 10), (11, 11), (10, 12)]
STAR = [(2, 0), (1, 1), (2, 1), (3, 1), (0, 2), (1, 2), (2, 2), (3, 2), (4, 2), (1, 3), (2, 3), (3, 3), (1, 4), (3, 4)]
FLAMES = [3, 9, 5, 12, 7, 14, 8, 11, 4, 10, 6, 13, 5]


def _pattern(kind, x, y, n):
    """Is shell cell (x, y) in the accent colour for pattern `kind` (n: a further hash byte)?"""
    if kind == 0:
        return False                                          # plain
    if kind == 1:
        return y in (8, 9)                                    # racing stripe
    if kind == 2:
        return y in (7, 10)                                   # twin stripes
    if kind == 3:
        return x < 12                                         # two-tone split
    if kind == 4:
        return ((x + y) // 3) % 2 == 0 and y >= 14            # diagonal stripes, lower shell
    if kind == 5:
        return (x // 3 + y // 3) % 2 == 0 and y >= 16         # checkers, lower shell
    if kind == 6:
        return x % 4 == 1 and y % 4 == 1                      # dots
    if kind == 7:
        return ((x - abs(y - 19)) // 3) % 2 == 0 and y >= 14  # chevrons
    if kind == 8:
        return y >= 14 and x >= 21 - FLAMES[(y - 14 + n % 4) % len(FLAMES)]   # flames licking back from the front
    if kind == 9:
        return (x, y) in BOLT or (x + 1, y) in BOLT           # lightning bolt
    if kind == 10:
        return (x - 5, y - 17) in STAR or (x - 14, y - 4) in STAR   # two stars
    return False


def _pixels(seed):
    d = hashlib.sha256(seed.encode("utf-8")).digest()
    shell = SHELLS[d[0] % len(SHELLS)]
    accent = ACCENTS[d[1] % len(ACCENTS)]
    if accent == shell:
        accent = ACCENTS[(d[1] + 1) % len(ACCENTS)]
    lens, bg = LENSES[d[2] % len(LENSES)], BACKGROUNDS[d[3] % len(BACKGROUNDS)]
    skin, skin_shadow = SKINS[d[9] % len(SKINS)]
    kind = d[4] % 12
    peak = accent if d[5] & 1 else shell
    number = d[6] % 100
    shape = _shape(peak=not d[8] & 1, round_goggles=bool(d[8] & 2), full_face=not d[8] & 4)
    grid = []
    for y, row in enumerate(shape):
        line = []
        for x, c in enumerate(row):
            if c == "S":
                colour = accent if _pattern(kind, x, y, d[7]) else shell
                if kind == 11 and 6 <= x <= 15 and 16 <= y <= 22:    # race-number plate
                    colour = PLATE
                    dx, dy = x - 7, y - 17
                    for i, digit in enumerate((number // 10, number % 10)):
                        gx = dx - i * 4
                        if 0 <= gx < 3 and 0 <= dy < 5 and DIGITS[digit][dy * 3 + gx] == "1":
                            colour = DIGIT
            else:
                colour = {".": bg, "O": OUTLINE, "P": peak, "g": FRAME, "G": lens, "C": shell, "V": VENT,
                          "L": TRIM, "H": SHINE, "p": OUTLINE, "c": OUTLINE, "K": OUTLINE, "F": skin,
                          "f": skin_shadow, "m": MOUTH}[c]
            line.append(colour)
        grid.append(line)
    return grid, bg


def _png_indexed(width, height, indices, palette):
    raw = b"".join(b"\x00" + bytes(indices[y * width:(y + 1) * width]) for y in range(height))
    blocks, i = [], 0
    while True:   # zlib stream with stored blocks: identical everywhere, no compressor involved
        part = raw[i:i + 65535]
        i += len(part)
        last = i >= len(raw)
        blocks.append(struct.pack("<BHH", 1 if last else 0, len(part), len(part) ^ 0xFFFF) + part)
        if last:
            break
    stream = b"\x78\x01" + b"".join(blocks) + struct.pack(">I", zlib.adler32(raw) & 0xFFFFFFFF)

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0)) +
            chunk(b"PLTE", b"".join(bytes(c) for c in palette)) + chunk(b"IDAT", stream) + chunk(b"IEND", b""))


def avatar_png(seed):
    """146x146 PNG for a rider id (or any string)."""
    grid, bg = _pixels(seed)
    palette, index = [], {}
    def idx(c):
        if c not in index:
            index[c] = len(palette)
            palette.append(c)
        return index[c]
    idx(bg)
    cells = [[idx(c) for c in row] for row in grid]
    out = bytearray(SIZE * SIZE)   # background is palette index 0
    for gy in range(GRID):
        for gx in range(GRID):
            v = cells[gy][gx]
            if v:
                for y in range(PAD + gy * CELL, PAD + gy * CELL + CELL):
                    out[y * SIZE + PAD + gx * CELL:y * SIZE + PAD + gx * CELL + CELL] = bytes([v]) * CELL
    return _png_indexed(SIZE, SIZE, out, palette)
