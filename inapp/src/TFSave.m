#import "TFSave.h"
#import <CommonCrypto/CommonDigest.h>
#import <zlib.h>

NSString *const TFNamespaceURL = @"6ba7b811-9dad-11d1-80b4-00c04fd430c8";
NSString *const TFNamespaceOID = @"6ba7b812-9dad-11d1-80b4-00c04fd430c8";

static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

uint32_t TFGameHash(NSString *s) {
    NSData *d = [s dataUsingEncoding:NSUTF8StringEncoding];
    const int8_t *b = d.bytes;
    uint32_t n = (uint32_t)d.length, x = 0;
    for (NSUInteger i = 0; i < d.length; i++) {
        x += n * (uint32_t)(int32_t)b[i];
        n = (n & 0xFFFF) * 18000 + (n >> 16);
    }
    return x;
}

NSData *TFUnscramble(NSData *data, uint32_t seed, uint32_t mult) {
    NSMutableData *out = [data mutableCopy];
    uint8_t *p = out.mutableBytes;
    uint32_t key = seed;
    for (NSUInteger i = 0; i < out.length; i++) {
        p[i] ^= (uint8_t)key;
        key *= mult;
    }
    return out;
}

NSData *TFInflate(NSData *data) {
    if (data.length == 0) return nil;
    z_stream s = {0};
    if (inflateInit(&s) != Z_OK) return nil;
    NSMutableData *out = [NSMutableData dataWithLength:MAX(data.length * 4, 4096)];
    s.next_in = (Bytef *)data.bytes;
    s.avail_in = (uInt)data.length;
    int r;
    do {
        if (s.total_out >= out.length) out.length *= 2;
        s.next_out = (Bytef *)out.mutableBytes + s.total_out;
        s.avail_out = (uInt)(out.length - s.total_out);
        r = inflate(&s, Z_NO_FLUSH);
    } while (r == Z_OK);
    NSUInteger total = s.total_out;
    inflateEnd(&s);
    if (r != Z_STREAM_END) return nil;
    out.length = total;
    return out;
}

NSData *TFDecodeSave(NSData *file) {
    if (file.length < 16) return nil;
    NSData *plain = TFUnscramble(file, 0x9D, 0x20B9);
    uint32_t size = rd32((const uint8_t *)plain.bytes + 8);
    NSData *body = [plain subdataWithRange:NSMakeRange(16, plain.length - 16)];
    return size ? TFInflate(body) : body;
}

static BOOL isRecord(const uint8_t *p) {
    uint32_t f0 = rd32(p), f8 = rd32(p + 32), f9 = rd32(p + 36), f10 = rd32(p + 40);
    // PlayerScores byte 0 changes after a race and id 0 (global_stats) appears after login, so only the integrity
    // copy and a plausible leaderboard id identify a record (as in scripts/extract_scores.py).
    return f0 < 0x1000000 && (f9 == 0 || (uint32_t)(f9 + f10 + f8 * 3600000u) == 360000000u);
}

NSDictionary<NSNumber *, NSArray<NSNumber *> *> *TFReadScores(NSData *raw) {
    const uint8_t *b = raw.bytes;
    NSUInteger len = raw.length;
    NSInteger bestStart = -1, bestN = 0, bestTimed = -1;
    for (NSUInteger start = 0; start + 68 < len; start += 4) {
        uint32_t n = rd32(b + start);
        if (n < 1 || n > 2000 || start + 4 + (NSUInteger)n * 64 > len) continue;
        BOOL ok = YES;
        NSInteger timed = 0;
        for (uint32_t i = 0; i < n && ok; i++) {
            const uint8_t *r = b + start + 4 + i * 64;
            ok = isRecord(r);
            if (rd32(r + 36)) timed++;
        }
        if (ok && timed > bestTimed) { bestStart = start; bestN = n; bestTimed = timed; }
    }
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    for (NSInteger i = 0; bestStart >= 0 && i < bestN; i++) {
        const uint8_t *r = b + bestStart + 4 + i * 64;
        if (rd32(r + 36)) out[@(rd32(r))] = @[@(rd32(r + 32)), @(rd32(r + 36)), @(rd32(r + 44))];
    }
    return out;
}

NSNumber *TFGhostDriveTime(NSData *ghost) {
    if (ghost.length < 16) return nil;
    uint32_t version = rd32(ghost.bytes);
    NSData *body = TFInflate([ghost subdataWithRange:NSMakeRange(16, ghost.length - 16)]);
    NSUInteger off = version >= 3 ? 4 : 0;
    if (body.length < off + 4) return nil;
    return @(rd32((const uint8_t *)body.bytes + off));
}

uint32_t TFGhostBike(NSData *ghost) {
    if (ghost.length < 16) return 0;
    NSData *body = TFInflate([ghost subdataWithRange:NSMakeRange(16, ghost.length - 16)]);
    return body.length >= 4 ? rd32(body.bytes) : 0;
}

NSData *TFRobotAvatarPNG(NSData *data) {
    if (data.length < 36) return nil;
    NSData *plain = TFUnscramble(data, 0x97, 0x1F49);
    NSData *body = [plain subdataWithRange:NSMakeRange(16, plain.length - 16)];
    if (memcmp(body.bytes, "OBOR", 4) != 0) return nil;
    static const uint8_t png[] = {0x89, 'P', 'N', 'G'};
    NSRange r = [body rangeOfData:[NSData dataWithBytes:png length:4] options:0 range:NSMakeRange(0, body.length)];
    return r.location == NSNotFound ? nil : [body subdataWithRange:NSMakeRange(r.location, body.length - r.location)];
}

static BOOL isLowerHex(uint8_t c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'); }

NSDictionary<NSString *, NSString *> *TFKnownRiders(NSData *raw) {
    const uint8_t *b = raw.bytes;
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    static const int dash[] = {8, 13, 18, 23};
    for (NSUInteger i = 129; i + 36 <= raw.length; i++) {
        BOOL ok = YES;
        for (int k = 0; k < 36 && ok; k++) {
            BOOL isDash = k == dash[0] || k == dash[1] || k == dash[2] || k == dash[3];
            ok = isDash ? b[i + k] == '-' : isLowerHex(b[i + k]);
        }
        if (!ok) continue;
        const uint8_t *name = b + i - 129;
        NSUInteger n = 0;
        while (n < 128 && name[n]) n++;
        BOOL printable = n >= 3 && n <= 32;
        for (NSUInteger k = 0; k < n && printable; k++) printable = name[k] >= 0x20 && name[k] <= 0x7E;
        if (printable) {
            out[[[NSString alloc] initWithBytes:b + i length:36 encoding:NSASCIIStringEncoding]] =
                [[NSString alloc] initWithBytes:name length:n encoding:NSASCIIStringEncoding];
        }
        i += 35;
    }
    return out;
}

static NSString *cstringAt(NSData *raw, NSUInteger off, NSUInteger max, NSStringEncoding enc) {
    if (raw.length < off + max) return @"";
    const char *p = (const char *)raw.bytes + off;
    NSUInteger n = 0;
    while (n < max && p[n]) n++;
    return [[NSString alloc] initWithBytes:p length:n encoding:enc] ?: @"";
}

void TFReadProfile(NSData *raw, NSString **name, NSString **profileId) {
    if (name) *name = cstringAt(raw, 20, 128, NSUTF8StringEncoding);
    if (profileId) *profileId = cstringAt(raw, 276, 40, NSASCIIStringEncoding);
}

NSString *TFUUID5(NSString *namespaceUUID, NSString *name) {
    uuid_t ns;
    [[[NSUUID alloc] initWithUUIDString:namespaceUUID] getUUIDBytes:ns];
    NSMutableData *in = [NSMutableData dataWithBytes:ns length:16];
    [in appendData:[name dataUsingEncoding:NSUTF8StringEncoding]];
    uint8_t h[CC_SHA1_DIGEST_LENGTH];
    CC_SHA1(in.bytes, (CC_LONG)in.length, h);
    h[6] = (h[6] & 0x0F) | 0x50;
    h[8] = (h[8] & 0x3F) | 0x80;
    return [[[NSUUID alloc] initWithUUIDBytes:h] UUIDString].lowercaseString;
}
