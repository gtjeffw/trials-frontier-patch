// Trials Frontier 7.9.0 file formats used by the local services (see docs/FORMATS.md and docs/JOURNAL.md).
// Mirrors the helpers in server/local_services.py and scripts/decode_save.py.
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// mt::String::getHashCode over the UTF-8 bytes (signed chars): x += n*c; n = (n & 0xffff) * 18000 + (n >> 16).
uint32_t TFGameHash(NSString *s);

/// SaveFile Protection XOR stream: byte ^= key & 0xff; key *= mult (32-bit).
NSData *TFUnscramble(NSData *data, uint32_t seed, uint32_t mult);

/// zlib inflate of a whole buffer; nil on error.
NSData *_Nullable TFInflate(NSData *data);

/// player.bin -> raw profile: unscramble (0x9D, 0x20B9), 16-byte header {version, checksum, size, 0}, zlib if size.
NSData *_Nullable TFDecodeSave(NSData *file);

/// Score table: leaderboard id -> @[faults, time ms, bike] for timed records (see scripts/extract_scores.py).
NSDictionary<NSNumber *, NSArray<NSNumber *> *> *TFReadScores(NSData *raw);

/// Drive time recorded in a ghost (16-byte header + zlib; v3 body: u32 bike, u32 time; v2: u32 time); nil if unreadable.
NSNumber *_Nullable TFGhostDriveTime(NSData *ghost);

/// First u32 of a ghost body (bike id for version 3), or 0.
uint32_t TFGhostBike(NSData *ghost);

/// robot_image-<hash>.robot: default Protection (0x97, 0x1F49), 16-byte header, 'OBOR' + 12 bytes + PNG.
NSData *_Nullable TFRobotAvatarPNG(NSData *data);

/// Profile id -> name pairs the save keeps for opponents (a name 129 bytes before its profile id).
NSDictionary<NSString *, NSString *> *TFKnownRiders(NSData *raw);

/// Player name (raw offset 20, Player+0x10) and profile id (raw offset 276, Player+0x110).
void TFReadProfile(NSData *raw, NSString *_Nullable *_Nullable name, NSString *_Nullable *_Nullable profileId);

/// RFC 4122 name-based UUID (version 5, SHA-1), lowercase with dashes; same as Python uuid.uuid5.
NSString *TFUUID5(NSString *namespaceUUID, NSString *name);

extern NSString *const TFNamespaceURL;  // 6ba7b811-9dad-11d1-80b4-00c04fd430c8
extern NSString *const TFNamespaceOID;  // 6ba7b812-9dad-11d1-80b4-00c04fd430c8

NS_ASSUME_NONNULL_END
