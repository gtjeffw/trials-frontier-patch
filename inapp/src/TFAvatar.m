// Port of server/avatars.py; keep the two identical (tests/test_parity.py compares their PNGs byte for byte).
#import "TFAvatar.h"
#import <CommonCrypto/CommonDigest.h>
#import <zlib.h>

enum { kSize = 146, kGrid = 32, kCell = kSize / kGrid, kPad = (kSize - kCell * kGrid) / 2 };

typedef struct { uint8_t r, g, b; } RGB;

// Tables generated from server/avatars.py (HELMET, FACE).
static const char *const kHelmet[32] = {
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
};
static const struct { int8_t x, y; char c; } kFace[99] = {
    {28, 12, 'F'}, {29, 12, 'F'}, {28, 13, 'F'}, {29, 13, 'F'}, {28, 14, 'F'}, {29, 14, 'F'}, {28, 15, 'F'},
    {29, 15, 'F'}, {30, 15, 'F'}, {28, 16, 'F'}, {29, 16, 'F'}, {30, 16, 'F'}, {20, 17, 'F'}, {21, 17, 'F'},
    {22, 17, 'F'}, {23, 17, 'F'}, {24, 17, 'F'}, {25, 17, 'F'}, {26, 17, 'F'}, {27, 17, 'F'}, {28, 17, 'F'},
    {29, 17, 'F'}, {30, 17, 'F'}, {20, 18, 'F'}, {21, 18, 'F'}, {22, 18, 'F'}, {23, 18, 'F'}, {24, 18, 'F'},
    {25, 18, 'F'}, {26, 18, 'F'}, {27, 18, 'F'}, {28, 18, 'F'}, {29, 18, 'F'}, {20, 19, 'F'}, {21, 19, 'F'},
    {22, 19, 'F'}, {23, 19, 'F'}, {24, 19, 'F'}, {25, 19, 'F'}, {26, 19, 'F'}, {27, 19, 'F'}, {28, 19, 'F'},
    {20, 20, 'F'}, {21, 20, 'F'}, {22, 20, 'F'}, {23, 20, 'F'}, {24, 20, 'F'}, {25, 20, 'F'}, {26, 20, 'F'},
    {27, 20, 'm'}, {28, 20, 'm'}, {20, 21, 'F'}, {21, 21, 'F'}, {22, 21, 'F'}, {23, 21, 'F'}, {24, 21, 'F'},
    {25, 21, 'F'}, {26, 21, 'F'}, {27, 21, 'F'}, {28, 21, 'F'}, {20, 22, 'F'}, {21, 22, 'F'}, {22, 22, 'F'},
    {23, 22, 'F'}, {24, 22, 'F'}, {25, 22, 'F'}, {26, 22, 'F'}, {27, 22, 'F'}, {28, 22, 'F'}, {20, 23, 'F'},
    {21, 23, 'F'}, {22, 23, 'F'}, {23, 23, 'F'}, {24, 23, 'F'}, {25, 23, 'F'}, {26, 23, 'F'}, {27, 23, 'F'},
    {19, 24, 'F'}, {20, 24, 'F'}, {21, 24, 'F'}, {22, 24, 'F'}, {23, 24, 'F'}, {24, 24, 'F'}, {25, 24, 'F'},
    {26, 24, 'O'}, {19, 25, 'f'}, {20, 25, 'f'}, {21, 25, 'f'}, {22, 25, 'f'}, {23, 25, 'f'}, {24, 25, 'f'},
    {25, 25, 'O'}, {19, 26, 'O'}, {20, 26, 'O'}, {21, 26, 'O'}, {22, 26, 'O'}, {23, 26, 'O'}, {24, 26, 'O'},
    {25, 26, 'O'},
};

static const RGB kShells[16] = {{214, 40, 40}, {232, 112, 22}, {240, 196, 25}, {124, 186, 36}, {32, 150, 72},
    {24, 160, 150}, {30, 120, 210}, {40, 64, 170}, {120, 60, 200}, {190, 50, 160}, {236, 236, 236}, {40, 40, 46},
    {150, 150, 158}, {120, 76, 40}, {250, 120, 150}, {0, 190, 220}};
static const RGB kAccents[12] = {{255, 255, 255}, {20, 20, 24}, {255, 210, 0}, {255, 90, 0}, {0, 200, 255},
    {230, 30, 60}, {60, 220, 90}, {160, 90, 255}, {255, 120, 200}, {200, 200, 210}, {0, 120, 255}, {255, 160, 40}};
static const RGB kLenses[6] = {{60, 70, 90}, {40, 140, 230}, {235, 175, 30}, {220, 60, 50}, {60, 200, 140}, {180, 110, 230}};
static const RGB kBackgrounds[8] = {{236, 230, 216}, {214, 228, 238}, {226, 238, 214}, {240, 222, 222},
    {230, 222, 240}, {244, 236, 206}, {214, 236, 232}, {226, 226, 230}};
static const RGB kSkins[5][2] = {{{255, 214, 178}, {214, 160, 120}}, {{236, 188, 140}, {190, 136, 92}},
    {{198, 140, 96}, {150, 98, 62}}, {{150, 98, 64}, {104, 64, 40}}, {{104, 66, 44}, {70, 42, 28}}};
static const RGB kOutline = {26, 26, 30}, kFrame = {34, 34, 40}, kVent = {20, 20, 24}, kTrim = {60, 60, 66},
    kPlate = {250, 250, 245}, kDigit = {20, 20, 24}, kShine = {255, 255, 255}, kMouth = {120, 40, 40};
static const char *const kDigits[10] = {"111101101101111", "010110010010111", "111001111100111", "111001111001111",
    "101101111001001", "111100111001111", "111100111101111", "111001010100100", "111101111101111", "111101111001111"};
static const int8_t kBolt[12][2] = {{15, 4}, {14, 5}, {13, 6}, {12, 7}, {11, 8}, {12, 8}, {13, 8}, {14, 8}, {13, 9},
    {12, 10}, {11, 11}, {10, 12}};
static const int8_t kStar[14][2] = {{2, 0}, {1, 1}, {2, 1}, {3, 1}, {0, 2}, {1, 2}, {2, 2}, {3, 2}, {4, 2}, {1, 3},
    {2, 3}, {3, 3}, {1, 4}, {3, 4}};
static const int kFlames[13] = {3, 9, 5, 12, 7, 14, 8, 11, 4, 10, 6, 13, 5};

static int floordiv(int a, int b) { int q = a / b; return (a % b != 0 && (a < 0) != (b < 0)) ? q - 1 : q; }
static int floormod(int a, int b) { int m = a % b; return (m != 0 && (m < 0) != (b < 0)) ? m + b : m; }
static BOOL eq(RGB a, RGB b) { return a.r == b.r && a.g == b.g && a.b == b.b; }

static BOOL inPairs(const int8_t (*pairs)[2], int n, int x, int y) {
    for (int i = 0; i < n; i++) if (pairs[i][0] == x && pairs[i][1] == y) return YES;
    return NO;
}

static BOOL isOneOf(char c, const char *set) { return c && strchr(set, c) != NULL; }

static void shapeGrid(char g[kGrid][kGrid + 1], BOOL peak, BOOL roundGoggles, BOOL fullFace) {
    for (int y = 0; y < kGrid; y++) memcpy(g[y], kHelmet[y], kGrid + 1);
    for (int y = 0; y < kGrid; y++)
        for (int x = 0; x < kGrid; x++)
            if ((!peak && isOneOf(g[y][x], "Pp")) || (!fullFace && isOneOf(g[y][x], "CVcK"))) g[y][x] = '.';
    if (!peak) g[7][27] = 'S';  // close the dome where the peak was
    if (roundGoggles) {
        for (int y = 12; y < 17; y++)
            for (int x = 20; x < 28; x++)
                if (isOneOf(g[y][x], "gG")) g[y][x] = 'S';
        for (int y = 9; y < 19; y++)
            for (int x = 19; x < 29; x++) {
                int r2 = (2 * x - 47) * (2 * x - 47) + (2 * y - 27) * (2 * y - 27);
                if (r2 <= 36) g[y][x] = (x == 22 && y == 12) ? 'H' : 'G';
                else if (r2 <= 64) g[y][x] = 'g';
            }
    }
    static const int d4[4][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}};
    if (!fullFace) {
        for (size_t i = 0; i < sizeof kFace / sizeof kFace[0]; i++)
            if (!isOneOf(g[kFace[i].y][kFace[i].x], "gGH")) g[kFace[i].y][kFace[i].x] = kFace[i].c;
        for (int y = 0; y < kGrid; y++)   // a dark line where the helmet meets the face
            for (int x = 0; x < kGrid; x++) {
                if (g[y][x] != 'S') continue;
                for (int k = 0; k < 4; k++) {
                    int nx = x + d4[k][0], ny = y + d4[k][1];
                    if (nx >= 0 && nx < kGrid && ny >= 0 && ny < kGrid && isOneOf(g[ny][nx], "Ffm")) { g[y][x] = 'K'; break; }
                }
            }
    }
    for (int y = 0; y < kGrid; y++)   // outline where shell now meets the background
        for (int x = 0; x < kGrid; x++) {
            if (!isOneOf(g[y][x], "SHLCKF")) continue;
            for (int k = 0; k < 4; k++) {
                int nx = x + d4[k][0], ny = y + d4[k][1];
                if (nx < 0 || nx >= kGrid || ny < 0 || ny >= kGrid || g[ny][nx] == '.') { g[y][x] = 'O'; break; }
            }
        }
}

static BOOL pattern(int kind, int x, int y, int n) {
    switch (kind) {
        case 1: return y == 8 || y == 9;                                         // racing stripe
        case 2: return y == 7 || y == 10;                                        // twin stripes
        case 3: return x < 12;                                                   // two-tone split
        case 4: return floormod(floordiv(x + y, 3), 2) == 0 && y >= 14;          // diagonal stripes
        case 5: return floormod(floordiv(x, 3) + floordiv(y, 3), 2) == 0 && y >= 16;   // checkers
        case 6: return floormod(x, 4) == 1 && floormod(y, 4) == 1;               // dots
        case 7: return floormod(floordiv(x - abs(y - 19), 3), 2) == 0 && y >= 14;      // chevrons
        case 8: return y >= 14 && x >= 21 - kFlames[floormod(y - 14 + floormod(n, 4), 13)];   // flames
        case 9: return inPairs(kBolt, 12, x, y) || inPairs(kBolt, 12, x + 1, y);  // lightning bolt
        case 10: return inPairs(kStar, 14, x - 5, y - 17) || inPairs(kStar, 14, x - 14, y - 4);   // two stars
        default: return NO;                                                      // plain (and 11: number)
    }
}

static void appendBE32(NSMutableData *d, uint32_t v) {
    uint8_t b[4] = {(uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
    [d appendBytes:b length:4];
}

static void appendChunk(NSMutableData *png, const char *type, NSData *data) {
    appendBE32(png, (uint32_t)data.length);
    NSMutableData *td = [NSMutableData dataWithBytes:type length:4];
    [td appendData:data];
    [png appendData:td];
    appendBE32(png, (uint32_t)crc32(0, td.bytes, (uInt)td.length));
}

NSData *TFAvatarPNG(NSString *seed) {
    NSData *s = [seed dataUsingEncoding:NSUTF8StringEncoding] ?: [NSData data];
    uint8_t d[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(s.bytes, (CC_LONG)s.length, d);
    RGB shell = kShells[d[0] % 16], accent = kAccents[d[1] % 12];
    if (eq(accent, shell)) accent = kAccents[(d[1] + 1) % 12];
    RGB lens = kLenses[d[2] % 6], bg = kBackgrounds[d[3] % 8];
    RGB skin = kSkins[d[9] % 5][0], skinShadow = kSkins[d[9] % 5][1];
    int kind = d[4] % 12;
    RGB peakColour = (d[5] & 1) ? accent : shell;
    int number = d[6] % 100;
    char g[kGrid][kGrid + 1];
    shapeGrid(g, !(d[8] & 1), (d[8] & 2) != 0, !(d[8] & 4));

    // colour every cell, then index the colours in order of first appearance (background first)
    RGB palette[64];
    int paletteCount = 0;
    palette[paletteCount++] = bg;
    uint8_t cells[kGrid][kGrid];
    for (int y = 0; y < kGrid; y++)
        for (int x = 0; x < kGrid; x++) {
            char c = g[y][x];
            RGB colour;
            if (c == 'S') {
                colour = pattern(kind, x, y, d[7]) ? accent : shell;
                if (kind == 11 && x >= 6 && x <= 15 && y >= 16 && y <= 22) {   // race-number plate
                    colour = kPlate;
                    int dx = x - 7, dy = y - 17;
                    int digits[2] = {number / 10, number % 10};
                    for (int i = 0; i < 2; i++) {
                        int gx = dx - i * 4;
                        if (gx >= 0 && gx < 3 && dy >= 0 && dy < 5 && kDigits[digits[i]][dy * 3 + gx] == '1') colour = kDigit;
                    }
                }
            } else {
                switch (c) {
                    case '.': colour = bg; break;
                    case 'P': colour = peakColour; break;
                    case 'g': colour = kFrame; break;
                    case 'G': colour = lens; break;
                    case 'C': colour = shell; break;
                    case 'V': colour = kVent; break;
                    case 'L': colour = kTrim; break;
                    case 'H': colour = kShine; break;
                    case 'F': colour = skin; break;
                    case 'f': colour = skinShadow; break;
                    case 'm': colour = kMouth; break;
                    default: colour = kOutline; break;   // O p c K
                }
            }
            int index = -1;
            for (int i = 0; i < paletteCount; i++) if (eq(palette[i], colour)) { index = i; break; }
            if (index < 0) { index = paletteCount; palette[paletteCount++] = colour; }
            cells[y][x] = (uint8_t)index;
        }

    // pixels: one filter byte (0) per row, then palette indices; 4x4 per cell inside a 9 px border
    NSMutableData *raw = [NSMutableData dataWithLength:kSize * (kSize + 1)];
    uint8_t *p = raw.mutableBytes;
    for (int gy = 0; gy < kGrid; gy++)
        for (int gx = 0; gx < kGrid; gx++)
            if (cells[gy][gx])
                for (int y = kPad + gy * kCell; y < kPad + gy * kCell + kCell; y++)
                    memset(p + y * (kSize + 1) + 1 + kPad + gx * kCell, cells[gy][gx], kCell);

    // zlib stream with stored blocks: identical everywhere, no compressor involved
    NSMutableData *stream = [NSMutableData dataWithBytes:"\x78\x01" length:2];
    NSUInteger i = 0;
    do {
        NSUInteger n = MIN((NSUInteger)65535, raw.length - i);
        BOOL last = i + n >= raw.length;
        uint8_t hdr[5] = {last ? 1 : 0, (uint8_t)n, (uint8_t)(n >> 8), (uint8_t)~n, (uint8_t)(~n >> 8)};
        [stream appendBytes:hdr length:5];
        [stream appendBytes:(const uint8_t *)raw.bytes + i length:n];
        i += n;
    } while (i < raw.length);
    appendBE32(stream, (uint32_t)adler32(adler32(0, NULL, 0), raw.bytes, (uInt)raw.length));

    NSMutableData *png = [NSMutableData dataWithBytes:"\x89PNG\r\n\x1a\n" length:8];
    NSMutableData *ihdr = [NSMutableData data];
    appendBE32(ihdr, kSize);
    appendBE32(ihdr, kSize);
    [ihdr appendBytes:"\x08\x03\x00\x00\x00" length:5];
    appendChunk(png, "IHDR", ihdr);
    NSMutableData *plte = [NSMutableData data];
    for (int k = 0; k < paletteCount; k++) [plte appendBytes:&palette[k] length:3];
    appendChunk(png, "PLTE", plte);
    appendChunk(png, "IDAT", stream);
    appendChunk(png, "IEND", [NSData data]);
    return png;
}
