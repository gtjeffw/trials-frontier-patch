#import <CommonCrypto/CommonDigest.h>
#import "TFServices.h"
#import "TFSave.h"
#import "TFAvatar.h"

static NSString *const kSandbox = @"triag_ip_lnch61_a_ws";
static NSString *const kCommunityFormat = @"trials-frontier-community";
static const NSInteger kCommunityBase = 1000000000;  // content ids of community ghosts
static NSString *const kGlobalBoard = @"global_stats";  // the Hall of Fame (overall score), not a track
// One Hall of Fame per score category: regular, Donkey (leaderboard class 0x10000), crazy bikes (0x100000)
static BOOL isHallOfFame(NSString *name) {
    return [@[kGlobalBoard, @"global_stats_donkey", @"global_stats_crazy"] containsObject:name];
}

static NSInteger I(id v) { return [v respondsToSelector:@selector(longLongValue)] ? (NSInteger)[v longLongValue] : 0; }

static NSString *isoTime(NSDate *d) {
    NSDateFormatter *f = [NSDateFormatter new];
    f.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    f.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    f.dateFormat = @"yyyy-MM-dd'T'HH:mm:ss'.000Z'";
    return [f stringFromDate:d];
}

static NSArray<NSString *> *match(NSString *pattern, NSString *s) {
    NSRegularExpression *re = [NSRegularExpression regularExpressionWithPattern:[NSString stringWithFormat:@"^(?:%@)$", pattern]
                                                                        options:0 error:nil];
    NSTextCheckingResult *m = [re firstMatchInString:s options:0 range:NSMakeRange(0, s.length)];
    if (!m) return nil;
    NSMutableArray *out = [NSMutableArray array];
    for (NSUInteger i = 1; i < m.numberOfRanges; i++) [out addObject:[s substringWithRange:[m rangeAtIndex:i]]];
    return out;
}

static NSInteger trailingNumber(NSString *s, BOOL *found) {
    NSRange r = [s rangeOfString:@"[0-9]+$" options:NSRegularExpressionSearch];
    if (found) *found = r.location != NSNotFound;
    return r.location == NSNotFound ? 0 : [[s substringWithRange:r] integerValue];
}

static id jsonObject(NSData *d) {
    if (!d.length) return nil;
    return [NSJSONSerialization JSONObjectWithData:d options:NSJSONReadingMutableContainers error:nil];
}

@implementation TFServices {
    NSString *_avatarsDir;
    void (^_log)(NSString *);
    NSString *_fixedName;
    NSDate *_saveDate;
    // community layer (see loadCommunity:): what it replaced, its ghosts and avatars
    NSMutableDictionary<NSString *, NSMutableDictionary *> *_shadowResults;  // board -> rider -> old entry or NSNull
    NSMutableDictionary *_shadowRiders;                                     // rider -> old entry or NSNull
    NSMutableSet<NSString *> *_communityGhosts;
    NSMutableDictionary<NSString *, NSString *> *_communityAvatars;
    NSString *_communityDir;
}

/// The names the server makes up for riders it knows only by hash.
static BOOL placeholder(NSString *name) {
    if (!name.length) return YES;
    return [name rangeOfString:@"^(?i)rider( [0-9A-F]{8})?$" options:NSRegularExpressionSearch].location != NSNotFound;
}

static NSString *sha256Hex(NSString *s) {
    NSData *d = [s dataUsingEncoding:NSUTF8StringEncoding];
    uint8_t h[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(d.bytes, (CC_LONG)d.length, h);
    NSMutableString *out = [NSMutableString string];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) [out appendFormat:@"%02x", h[i]];
    return out;
}

/// The new name in the mobile login library's "change account name" request (ubimobile changeAccountName, sent when
/// the player picks a name in the tutorial or the options): "Authorization: UbiMobile_v1 t=<base64 of
/// account:secret:base64(name)>" (a plain login has two fields). nil for any other request.
/// For the log: how many fields the login token has and the name in it (never the secret).
static NSString *tokenSummary(TFRequest *q) {
    NSString *auth = q.headers[@"authorization"] ?: @"";
    NSRange r = [auth rangeOfString:@"t="];
    if (r.location == NSNotFound) return [NSString stringWithFormat:@"no token (%@)", auth.length ? [auth componentsSeparatedByString:@" "][0] : @"none"];
    NSData *outer = [[NSData alloc] initWithBase64EncodedString:[auth substringFromIndex:NSMaxRange(r)] options:0];
    NSArray *parts = [[[NSString alloc] initWithData:outer ?: [NSData data] encoding:NSUTF8StringEncoding] componentsSeparatedByString:@":"];
    NSString *name = @"-";
    if (parts.count >= 3) {
        NSData *inner = [[NSData alloc] initWithBase64EncodedString:parts[2] options:0];
        name = inner ? [[NSString alloc] initWithData:inner encoding:NSUTF8StringEncoding] ?: @"?" : @"?";
    }
    return [NSString stringWithFormat:@"%lu fields, name '%@'", (unsigned long)parts.count, name];
}

static NSString *requestedName(TFRequest *q) {
    NSString *auth = [q.headers[@"authorization"] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
    if (![auth hasPrefix:@"UbiMobile_v1 t="]) return nil;
    NSData *outer = [[NSData alloc] initWithBase64EncodedString:[auth substringFromIndex:15] options:0];
    NSString *text = outer ? [[NSString alloc] initWithData:outer encoding:NSUTF8StringEncoding] : nil;
    NSArray *parts = [text componentsSeparatedByString:@":"];
    if (parts.count != 3) return nil;
    NSData *inner = [[NSData alloc] initWithBase64EncodedString:parts[2] options:0];
    NSString *name = inner ? [[NSString alloc] initWithData:inner encoding:NSUTF8StringEncoding] : nil;
    if (!name.length || name.length > 32 || placeholder(name)) return nil;  // a normal login echoes our placeholder
    for (NSUInteger i = 0; i < name.length; i++)
        if ([NSCharacterSet.controlCharacterSet characterIsMember:[name characterAtIndex:i]]) return nil;
    return name;
}

static BOOL isUUID(NSString *s) {
    return [s rangeOfString:@"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$" options:NSRegularExpressionSearch].location != NSNotFound;
}

- (instancetype)initWithDocuments:(NSString *)documentsDir dataDir:(NSString *)dataDir port:(uint16_t)port
                        profileId:(NSString *)profileId name:(NSString *)name avatarsDir:(NSString *)avatarsDir
                              log:(void (^)(NSString *))log {
    if ((self = [super init])) {
        _documentsDir = [documentsDir copy];
        _dataDir = [dataDir copy];
        _avatarsDir = [avatarsDir copy];
        _log = log;
        _base = [NSString stringWithFormat:@"http://127.0.0.1:%u", port];
        _lock = [NSRecursiveLock new];
        if (!profileId.length) {
            NSString *p = nil;
            TFReadProfile([self saveRaw] ?: [NSData data], NULL, &p);
            profileId = p;
        }
        _profileId = [profileId copy] ?: @"";  // empty for a new player until loadStore
        _fixedName = name.length ? [name copy] : nil;
        _name = @"Rider";
        [self refreshName];
    }
    return self;
}

/// The player's name: the one given, else the save's (re-read when player.bin changes: a new player picks one in the
/// tutorial), else "Rider".
- (void)refreshName {
    if (_fixedName) {
        _name = _fixedName;
        return;
    }
    // the last name the game asked for (change-name request); the save only catches up later
    [_lock lock];
    NSString *chosen = [_store[@"player_name"] isKindOfClass:NSString.class] ? _store[@"player_name"] : nil;
    if (chosen.length) _name = [chosen copy];
    [_lock unlock];
    if (chosen.length) return;
    NSDate *d = [NSFileManager.defaultManager attributesOfItemAtPath:[self documents:@"player.bin"] error:nil].fileModificationDate;
    [_lock lock];
    if (d && ![d isEqual:_saveDate]) {
        _saveDate = d;
        NSString *n = nil;
        TFReadProfile([self saveRaw] ?: [NSData data], &n, NULL);
        if (n.length) _name = [n copy];
    }
    [_lock unlock];
}

- (NSString *)ticket {
    return [@"local-" stringByAppendingString:[TFUUID5(TFNamespaceURL, _profileId) stringByReplacingOccurrencesOfString:@"-" withString:@""]];
}

- (void)note:(NSString *)line { _log(line); }

- (NSString *)documents:(NSString *)name { return [_documentsDir stringByAppendingPathComponent:name]; }

- (NSData *)saveRaw {
    NSData *f = [NSData dataWithContentsOfFile:[self documents:@"player.bin"]];
    return f ? TFDecodeSave(f) : nil;
}

- (NSDictionary *)scores { return TFReadScores([self saveRaw] ?: [NSData data]); }

#pragma mark - store

- (void)loadStore:(NSString *)communityDir {
    [_lock lock];
    _shadowResults = [NSMutableDictionary dictionary];
    _shadowRiders = [NSMutableDictionary dictionary];
    _communityGhosts = [NSMutableSet set];
    _communityAvatars = [NSMutableDictionary dictionary];
    _communityDir = nil;
    NSFileManager *fm = NSFileManager.defaultManager;
    [fm createDirectoryAtPath:[_dataDir stringByAppendingPathComponent:@"ghosts"] withIntermediateDirectories:YES attributes:nil error:nil];
    NSMutableDictionary *s = jsonObject([NSData dataWithContentsOfFile:[_dataDir stringByAppendingPathComponent:@"store.json"]]);
    _store = s ?: [@{@"results": [NSMutableDictionary dictionary], @"ghosts": [NSMutableDictionary dictionary], @"next_id": @1000} mutableCopy];
    if (!_profileId.length) {  // a new player: no save yet; the game keeps the id the login returns
        if (!_store[@"new_player_profile"]) _store[@"new_player_profile"] = NSUUID.UUID.UUIDString.lowercaseString;
        _profileId = [_store[@"new_player_profile"] copy];
    }
    NSInteger seeded = 0;
    NSDictionary *scores = [self scores];
    for (NSNumber *lb in scores) {
        NSArray *sc = scores[lb];
        NSString *key = [NSString stringWithFormat:@"track%u", lb.unsignedIntValue];
        NSMutableDictionary *board = _store[@"results"][key] ?: (_store[@"results"][key] = [NSMutableDictionary dictionary]);
        if (!board[_profileId]) {
            NSInteger faults = I(sc[0]), ms = I(sc[1]), bike = I(sc[2]);
            board[_profileId] = [@{@"drivetime": @(ms), @"data": @((faults & 0xFF) | ((bike & 0x3F) << 8)), @"upgrades": @0,
                                   @"submittime": @0, @"score_value": @(360000000 - ms - faults * 3600000), @"extradata": @0,
                                   @"source": @"save"} mutableCopy];
            seeded++;
        }
    }
    NSString *prefix = [NSString stringWithFormat:@"ghost_%08x_", TFGameHash(_profileId)];
    NSMutableSet *held = [NSMutableSet set];
    for (NSDictionary *g in [_store[@"ghosts"] allValues])
        if ([g[@"profile"] isEqual:_profileId]) [held addObject:@(I(g[@"track_id"]))];
    NSArray *files = [[fm contentsOfDirectoryAtPath:_documentsDir error:nil] sortedArrayUsingSelector:@selector(compare:)];
    for (NSString *f in files) {
        if (![f hasPrefix:prefix]) continue;
        NSArray *m = match([[NSRegularExpression escapedPatternForString:prefix] stringByAppendingString:@"([0-9]+)\\.bin"], f);
        if (!m) continue;
        NSInteger lb = [m[0] integerValue];
        if ([held containsObject:@(lb)]) continue;  // the store's own (possibly newer) ghost wins
        NSData *data = [NSData dataWithContentsOfFile:[self documents:f]];
        NSInteger cid = [self newId];
        [data writeToFile:[self ghostPath:@(cid)] atomically:YES];
        NSInteger ms = I(TFGhostDriveTime(data));
        if (!ms) ms = I(scores[@(lb)][1]);
        _store[@"ghosts"][[@(cid) stringValue]] = [@{@"profile": _profileId, @"track_id": @(lb), @"source": f,
                                                     @"metadata": [@{@"track_id": @(lb), @"size": @(data.length), @"drive_time": @(ms)} mutableCopy]} mutableCopy];
        seeded++;
    }
    if (!_store[@"riders"]) _store[@"riders"] = [NSMutableDictionary dictionary];
    seeded += [self importRobots];
    [self dropLegacyWorldRecords];
    [self loadCommunity:communityDir ?: [_dataDir stringByAppendingPathComponent:@"community"]];
    [self saveStore];
    NSInteger results = 0;
    for (NSDictionary *b in [_store[@"results"] allValues]) results += b.count;
    [self note:[NSString stringWithFormat:@"store %@: %ld results, %lu ghosts, %lu other riders (%ld imported now, %lu ghosts from the community layer)",
                _dataDir, (long)results, (unsigned long)[_store[@"ghosts"] count], (unsigned long)[_store[@"riders"] count],
                (long)seeded, (unsigned long)_communityGhosts.count]];
    [_lock unlock];
}

/// World records used to be imported into the store; they now come from the community layer.
- (void)dropLegacyWorldRecords {
    if (!_store[@"world_records_imported"]) return;
    [_store removeObjectForKey:@"world_records_imported"];
    NSMutableSet *gone = [NSMutableSet set];
    for (NSString *rid in [_store[@"riders"] allKeys])
        if ([_store[@"riders"][rid][@"source"] isEqual:@"wr2019"]) [gone addObject:rid];
    [_store[@"riders"] removeObjectsForKeys:gone.allObjects];
    for (NSString *name in [_store[@"results"] allKeys]) {
        NSMutableDictionary *board = _store[@"results"][name];
        for (NSString *rid in board.allKeys)
            if ([board[rid][@"source"] isEqual:@"wr2019"]) [board removeObjectForKey:rid];
        if (!board.count) [_store[@"results"] removeObjectForKey:name];
    }
    [self note:[NSString stringWithFormat:@"removed %lu world-record riders imported by an older version (now: community layer)",
                (unsigned long)gone.count]];
}

/// Overlay the community layer (scripts/community.py): riders merge by the game's hash of their profile id, a layer
/// result shows only where it beats the stored one, layer ghosts keep their own content ids and files, the player's
/// own rider is skipped (only its avatar is used). Nothing of it is written into store.json (see -persisted).
- (void)loadCommunity:(NSString *)folder {
    NSString *path = [folder stringByAppendingPathComponent:@"community.json"];
    if (![NSFileManager.defaultManager fileExistsAtPath:path]) return;
    NSDictionary *layer = jsonObject([NSData dataWithContentsOfFile:path]);
    if (![layer isKindOfClass:NSDictionary.class] || ![layer[@"format"] isEqual:kCommunityFormat] || I(layer[@"format_version"]) != 1 ||
        ![layer[@"riders"] isKindOfClass:NSDictionary.class] || ![layer[@"results"] isKindOfClass:NSDictionary.class] ||
        ![layer[@"ghosts"] isKindOfClass:NSDictionary.class]) {
        [self note:[NSString stringWithFormat:@"community layer %@: unreadable or unsupported format; ignored", folder]];
        return;
    }
    _communityDir = [folder copy];
    NSString *own = [NSString stringWithFormat:@"%08X", TFGameHash(_profileId)];
    NSString *ownSha = sha256Hex([@"trials-frontier-profile:" stringByAppendingString:_profileId]);
    NSMutableDictionary *byHash = [NSMutableDictionary dictionary];
    for (NSString *r in [[_store[@"riders"] allKeys] sortedArrayUsingSelector:@selector(compare:)])
        if (isUUID(r)) byHash[[NSString stringWithFormat:@"%08X", TFGameHash(r)]] = r;
    NSCountedSet *hashCount = [NSCountedSet set];
    for (NSDictionary *c in [layer[@"riders"] allValues])
        if ([c[@"game_hash"] isKindOfClass:NSString.class]) [hashCount addObject:c[@"game_hash"]];
    NSMutableDictionary *ridMap = [NSMutableDictionary dictionary];
    NSFileManager *fm = NSFileManager.defaultManager;
    for (NSString *crid in [[layer[@"riders"] allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
        NSDictionary *c = layer[@"riders"][crid];
        NSString *h = [c[@"game_hash"] isKindOfClass:NSString.class] ? c[@"game_hash"] : nil;
        NSString *avatar = [[folder stringByAppendingPathComponent:@"avatars"] stringByAppendingPathComponent:[crid stringByAppendingString:@".png"]];
        BOOL hasAvatar = [fm fileExistsAtPath:avatar];
        // the player: by the sha256 of the profile id; a rider known only by the 32-bit hash, by the hash
        NSString *sha = [c[@"profile_sha256"] isKindOfClass:NSString.class] ? c[@"profile_sha256"] : nil;
        if ([sha isEqual:ownSha] || (h.length && [h isEqual:own] && !sha)) {
            if (hasAvatar && [sha isEqual:ownSha]) _communityAvatars[_profileId] = avatar;
            continue;
        }
        // a downloaded opponent already in the store: linked by the hash only if no other layer rider has it
        NSString *rid = crid;
        if (!_store[@"riders"][crid] && h.length && [hashCount countForObject:h] == 1) {
            NSString *robot = TFUUID5(TFNamespaceURL, [@"trials-frontier-robot:" stringByAppendingString:h]);
            rid = _store[@"riders"][robot] ? robot : (byHash[h] ?: crid);
        }
        ridMap[crid] = rid;
        if (hasAvatar) _communityAvatars[rid] = avatar;
        NSDictionary *cur = _store[@"riders"][rid];
        NSString *name = [c[@"name"] isKindOfClass:NSString.class] ? c[@"name"] : nil;
        if (!cur || (placeholder(cur[@"name"]) && !placeholder(name))) {
            if (!_shadowRiders[rid]) _shadowRiders[rid] = cur ?: (id)NSNull.null;
            _store[@"riders"][rid] = [@{@"name": name.length ? name : [@"Rider " stringByAppendingString:h ?: @"?"],
                                        @"source": @"community"} mutableCopy];
        }
    }
    NSInteger shown = 0;
    for (NSString *name in [[layer[@"results"] allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
        NSDictionary *entries = layer[@"results"][name];
        for (NSString *crid in [[entries allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
            NSString *rid = ridMap[crid];
            if (!rid) continue;
            NSMutableDictionary *board = _store[@"results"][name] ?: (_store[@"results"][name] = [NSMutableDictionary dictionary]);
            NSDictionary *old = board[rid];
            if (!better(entries[crid], old)) continue;
            NSMutableDictionary *sb = _shadowResults[name] ?: (_shadowResults[name] = [NSMutableDictionary dictionary]);
            if (!sb[rid]) {
                sb[rid] = old ?: (id)NSNull.null;
                shown++;
            }
            board[rid] = [entries[crid] mutableCopy];
        }
    }
    NSArray *cids = [[layer[@"ghosts"] allKeys] sortedArrayUsingComparator:^NSComparisonResult(NSString *a, NSString *b) {
        return [@(a.longLongValue) compare:@(b.longLongValue)];
    }];
    for (NSString *cid in cids) {
        NSDictionary *g = layer[@"ghosts"][cid];
        NSString *rid = ridMap[g[@"profile"]];
        if (!rid || cid.longLongValue < kCommunityBase || _store[@"ghosts"][cid]) continue;
        NSMutableDictionary *e = [g mutableCopy];
        e[@"profile"] = rid;
        _store[@"ghosts"][cid] = e;
        [_communityGhosts addObject:cid];
    }
    [self note:[NSString stringWithFormat:@"community layer %@: %lu riders, %ld results shown, %lu ghosts", folder,
                (unsigned long)ridMap.count, (long)shown, (unsigned long)_communityGhosts.count]];
}

/// The store without the community layer.
- (NSDictionary *)persisted {
    if (!_shadowResults.count && !_shadowRiders.count && !_communityGhosts.count) return _store;
    NSMutableDictionary *out = [_store mutableCopy];
    NSMutableDictionary *results = [_store[@"results"] mutableCopy];
    for (NSString *name in _shadowResults) {
        NSMutableDictionary *board = [results[name] mutableCopy];
        [_shadowResults[name] enumerateKeysAndObjectsUsingBlock:^(NSString *rid, id old, BOOL *stop) {
            if (old == NSNull.null) [board removeObjectForKey:rid];
            else board[rid] = old;
        }];
        if (board.count) results[name] = board;
        else [results removeObjectForKey:name];  // a board only the layer had
    }
    out[@"results"] = results;
    NSMutableDictionary *riders = [_store[@"riders"] mutableCopy];
    [_shadowRiders enumerateKeysAndObjectsUsingBlock:^(NSString *rid, id old, BOOL *stop) {
        if (old == NSNull.null) [riders removeObjectForKey:rid];
        else riders[rid] = old;
    }];
    out[@"riders"] = riders;
    NSMutableDictionary *ghosts = [_store[@"ghosts"] mutableCopy];
    [ghosts removeObjectsForKeys:_communityGhosts.allObjects];
    out[@"ghosts"] = ghosts;
    return out;
}

- (void)saveStore {
    [_lock lock];
    NSData *d = [NSJSONSerialization dataWithJSONObject:[self persisted] options:NSJSONWritingPrettyPrinted | NSJSONWritingWithoutEscapingSlashes error:nil];
    [d writeToFile:[_dataDir stringByAppendingPathComponent:@"store.json"] atomically:YES];
    [_lock unlock];
}

- (NSInteger)newId {
    [_lock lock];
    NSInteger cid = I(_store[@"next_id"]);
    _store[@"next_id"] = @(cid + 1);
    [_lock unlock];
    return cid;
}

- (NSString *)ghostPath:(id)cid {
    NSString *key = [NSString stringWithFormat:@"%ld", (long)I(cid)];
    if ([_communityGhosts containsObject:key])
        return [[_communityDir stringByAppendingPathComponent:@"ghosts"] stringByAppendingPathComponent:[key stringByAppendingString:@".bin"]];
    return [[_dataDir stringByAppendingPathComponent:@"ghosts"] stringByAppendingPathComponent:[NSString stringWithFormat:@"%ld.bin", (long)I(cid)]];
}

- (void)addRider:(NSString *)riderId name:(NSString *)name source:(NSString *)source {
    if (!_store[@"riders"][riderId]) _store[@"riders"][riderId] = [@{@"name": name, @"source": source} mutableCopy];
}

static BOOL better(NSDictionary *new, NSDictionary *old) {
    if (!old) return YES;
    NSInteger nf = I(new[@"data"]) & 0xFF, of = I(old[@"data"]) & 0xFF;
    return nf < of || (nf == of && I(new[@"drivetime"]) < I(old[@"drivetime"]));
}

- (BOOL)addResult:(NSString *)boardName rider:(NSString *)riderId faults:(NSInteger)faults ms:(NSInteger)ms bike:(NSInteger)bike
           source:(NSString *)source {
    NSMutableDictionary *board = _store[@"results"][boardName] ?: (_store[@"results"][boardName] = [NSMutableDictionary dictionary]);
    NSDictionary *new = @{@"drivetime": @(ms), @"data": @((faults & 0xFF) | ((bike & 0x3F) << 8)), @"upgrades": @0, @"submittime": @0,
                          @"score_value": @(360000000 - ms - faults * 3600000), @"extradata": @0, @"source": source};
    if (!better(new, board[riderId])) return NO;
    board[riderId] = [new mutableCopy];
    return YES;
}

- (NSInteger)importRobots {
    if ([_store[@"robots_imported"] boolValue]) return 0;
    NSMutableDictionary *named = [NSMutableDictionary dictionary];
    NSDictionary *known = TFKnownRiders([self saveRaw] ?: [NSData data]);
    for (NSString *pid in known) named[[NSString stringWithFormat:@"%08X", TFGameHash(pid)]] = @[pid, known[pid]];
    NSInteger count = 0;
    NSString *avatars = [_dataDir stringByAppendingPathComponent:@"avatars"];
    [NSFileManager.defaultManager createDirectoryAtPath:avatars withIntermediateDirectories:YES attributes:nil error:nil];
    NSArray *files = [[NSFileManager.defaultManager contentsOfDirectoryAtPath:_documentsDir error:nil] sortedArrayUsingSelector:@selector(compare:)];
    for (NSString *f in files) {
        NSArray *m = match(@"robot_ghost-([0-9A-F]+)-([0-9A-F]+)\\.robot", f);
        if (!m) continue;
        NSString *h = [[@"00000000" substringToIndex:MAX(0, 8 - (NSInteger)[m[0] length])] stringByAppendingString:m[0]];
        unsigned lb = 0;
        [[NSScanner scannerWithString:m[1]] scanHexInt:&lb];
        NSData *data = [NSData dataWithContentsOfFile:[self documents:f]];
        NSInteger ms = I(TFGhostDriveTime(data));
        if (!ms) continue;
        NSArray *k = named[h];
        NSString *rid = k ? k[0] : TFUUID5(TFNamespaceURL, [@"trials-frontier-robot:" stringByAppendingString:h]);
        [self addRider:rid name:k ? k[1] : [@"Rider " stringByAppendingString:h] source:@"robot"];
        count += [self addResult:[NSString stringWithFormat:@"track%u", lb] rider:rid faults:0 ms:ms bike:TFGhostBike(data) source:@"robot"];
        NSInteger cid = [self newId];
        [data writeToFile:[self ghostPath:@(cid)] atomically:YES];
        _store[@"ghosts"][[@(cid) stringValue]] = [@{@"profile": rid, @"track_id": @(lb), @"source": f,
                                                     @"metadata": [@{@"track_id": @(lb), @"drive_time": @(ms), @"size": @(data.length)} mutableCopy]} mutableCopy];
        NSData *img = [NSData dataWithContentsOfFile:[self documents:[NSString stringWithFormat:@"robot_image-%@.robot", m[0]]]];
        NSData *png = img ? TFRobotAvatarPNG(img) : nil;
        if (png) [png writeToFile:[avatars stringByAppendingPathComponent:[rid stringByAppendingString:@".png"]] atomically:YES];
    }
    _store[@"robots_imported"] = @YES;
    return count;
}

#pragma mark - leaderboards and results

- (NSDictionary *)board:(NSString *)name {
    NSDictionary *results = _store[@"results"];
    if (results[name]) return results[name];
    NSArray *m = match(@"track([0-9]+)", name);
    if (m) {
        NSInteger base = [m[0] integerValue];
        for (NSString *key in [results.allKeys sortedArrayUsingSelector:@selector(compare:)]) {
            NSArray *k = match(@"track([0-9]+)", key);
            if (k && ([k[0] longLongValue] & 0xFFFF) == base) return results[key];
        }
    }
    return @{};
}

- (NSDictionary *)leaderboard:(NSString *)name request:(TFRequest *)req {
    [_lock lock];
    NSDictionary *board = [[self board:name] copy];
    [_lock unlock];
    BOOL hallOfFame = isHallOfFame(name);  // highest overall score first
    NSArray *pids = [board.allKeys sortedArrayUsingComparator:^NSComparisonResult(NSString *a, NSString *b) {
        if (hallOfFame) {
            double ga = [board[a][@"global_score"] doubleValue], gb = [board[b][@"global_score"] doubleValue];
            if (ga != gb) return ga > gb ? NSOrderedAscending : NSOrderedDescending;
            return [a compare:b];
        }
        NSInteger fa = I(board[a][@"data"]) & 0xFF, fb = I(board[b][@"data"]) & 0xFF;
        if (fa != fb) return fa < fb ? NSOrderedAscending : NSOrderedDescending;
        NSInteger ta = I(board[a][@"drivetime"]), tb = I(board[b][@"drivetime"]);
        if (ta != tb) return ta < tb ? NSOrderedAscending : NSOrderedDescending;
        return [a compare:b];
    }];
    NSMutableArray *rows = [NSMutableArray array];
    for (NSUInteger i = 0; i < pids.count; i++) {
        NSMutableDictionary *st = [board[pids[i]] mutableCopy];
        [st removeObjectForKey:@"source"];
        [rows addObject:@{@"player": pids[i], @"rank": @(i + 1), @"stats": st}];
    }
    NSUInteger total = rows.count;
    NSArray *out = rows;
    if (req.query[@"players"]) {
        NSSet *wanted = [NSSet setWithArray:[req listParam:@"players"]];
        out = [rows filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSDictionary *r, id _) { return [wanted containsObject:r[@"player"]]; }]];
    } else if (req.query[@"range"]) {
        NSArray *ab = [[req param:@"range"] componentsSeparatedByString:@","];
        NSInteger a = MAX([ab[0] integerValue], 1) - 1, b = ab.count > 1 ? [ab[1] integerValue] : 0;
        out = a < b && a < (NSInteger)rows.count ? [rows subarrayWithRange:NSMakeRange(a, MIN(b, (NSInteger)rows.count) - a)] : @[];
    } else if (req.query[@"around"]) {
        NSString *around = [req param:@"around"];
        NSRange comma = [around rangeOfString:@","];
        NSString *pid = comma.location == NSNotFound ? around : [around substringToIndex:comma.location];
        NSInteger n = comma.location == NSNotFound ? 10 : [[around substringFromIndex:comma.location + 1] integerValue];
        if (n == 0) n = 10;
        NSInteger i = 0;
        for (NSUInteger k = 0; k < rows.count; k++) if ([rows[k][@"player"] isEqual:pid]) { i = k; break; }
        NSInteger start = MAX(0, i - n / 2), end = MIN((NSInteger)rows.count, start + n);
        out = start < end ? [rows subarrayWithRange:NSMakeRange(start, end - start)] : @[];
    }
    return @{@"leaderboard": name, @"playerCount": @(total), @"results": out};
}

- (BOOL)submit:(NSString *)name update:(NSDictionary *)update {
    NSDictionary *st = [update[@"stats"] isKindOfClass:NSDictionary.class] ? update[@"stats"] : update;
    NSMutableDictionary *new = [NSMutableDictionary dictionary];
    for (NSString *k in @[@"drivetime", @"data", @"upgrades", @"submittime", @"score_value", @"extradata"]) new[k] = st[k] ?: @0;
    if (!I(new[@"drivetime"])) return NO;
    [_lock lock];
    NSMutableDictionary *board = _store[@"results"][name] ?: (_store[@"results"][name] = [NSMutableDictionary dictionary]);
    NSDictionary *old = board[_profileId];
    BOOL improved = better(new, old);
    if (improved) {
        board[_profileId] = new;
        [self saveStore];
    }
    [_lock unlock];
    [self note:[NSString stringWithFormat:@"   result %@: %ldF %ld ms -> %@", name, (long)(I(new[@"data"]) & 0xFF), (long)I(new[@"drivetime"]),
                improved ? @"NEW BEST" : [NSString stringWithFormat:@"not better than %ldF %ld ms", (long)(I(old[@"data"]) & 0xFF), (long)I(old[@"drivetime"])]]];
    return improved;
}

/// Hall of Fame: the overall score the game computes from all its best times and sends after every race (POST
/// playerstats/v1/stats/global_stats; shown as global_score x 100000). One entry per player in the "global_stats"
/// board, replaced by each newer value: an aggregate, not a copy of the track results. Donkey and crazy-bike runs
/// send their own category's score to global_stats_donkey / global_stats_crazy.
- (BOOL)submitGlobal:(NSDictionary *)update board:(NSString *)name {
    NSDictionary *st = [update[@"stats"] isKindOfClass:NSDictionary.class] ? update[@"stats"] : update;
    if (![st[@"global_score"] isKindOfClass:NSNumber.class]) return NO;
    double score = [st[@"global_score"] doubleValue];
    NSMutableDictionary *new = [@{@"global_score": @(score)} mutableCopy];
    for (NSString *k in @[@"data", @"drivetime", @"upgrades", @"submittime"]) new[k] = st[k] ?: @0;
    [_lock lock];
    NSMutableDictionary *board = _store[@"results"][name] ?: (_store[@"results"][name] = [NSMutableDictionary dictionary]);
    NSDictionary *old = board[_profileId];
    BOOL changed = !old || [old[@"global_score"] doubleValue] != score;
    if (changed) {
        board[_profileId] = new;
        [self saveStore];
    }
    [_lock unlock];
    NSNumberFormatter *f = [NSNumberFormatter new];
    f.numberStyle = NSNumberFormatterDecimalStyle;
    f.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    f.usesGroupingSeparator = YES;
    f.groupingSize = 3;
    NSString *label = [name isEqualToString:kGlobalBoard] ? @""
                      : [NSString stringWithFormat:@" (%@)", [name substringFromIndex:kGlobalBoard.length + 1]];
    [self note:[NSString stringWithFormat:@"   hall of fame%@: %@%@", label, [f stringFromNumber:@((long long)(score * 100000))],
                changed ? @"" : @" (unchanged)"]];
    return changed;
}

- (NSArray *)parseUpdates:(NSData *)body {
    id req = jsonObject(body);
    if (!req) {
        NSString *t = [[NSString alloc] initWithData:body encoding:NSUTF8StringEncoding] ?: @"";
        t = [t stringByReplacingOccurrencesOfString:@",\\s*([}\\]])" withString:@"$1" options:NSRegularExpressionSearch range:NSMakeRange(0, t.length)];
        req = jsonObject([t dataUsingEncoding:NSUTF8StringEncoding]);
    }
    id ups = [req isKindOfClass:NSDictionary.class] ? req[@"updates"] : nil;
    if (!ups) return @[];
    return [ups isKindOfClass:NSArray.class] ? ups : @[ups];
}

#pragma mark - ghosts (user storage)

- (NSArray<NSArray *> *)ghostsFor:(NSString *)profile track:(NSInteger)track {
    [_lock lock];
    NSMutableArray *out = [NSMutableArray array];
    [_store[@"ghosts"] enumerateKeysAndObjectsUsingBlock:^(NSString *cid, NSDictionary *g, BOOL *stop) {
        NSInteger t = I(g[@"track_id"]);
        if ([g[@"profile"] isEqual:profile] && (g[@"payload"] == nil || [g[@"payload"] boolValue]) && (t == track || (t & 0xFFFF) == track))
            [out addObject:@[@(cid.integerValue), g]];
    }];
    [_lock unlock];
    [out sortUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
        BOOL xa = I(a[1][@"track_id"]) != track, xb = I(b[1][@"track_id"]) != track;
        if (xa != xb) return xa ? NSOrderedDescending : NSOrderedAscending;
        NSInteger da = I(a[1][@"metadata"][@"drive_time"]) ?: (1L << 31), db = I(b[1][@"metadata"][@"drive_time"]) ?: (1L << 31);
        if (da != db) return da < db ? NSOrderedAscending : NSOrderedDescending;
        return [a[0] compare:b[0]];
    }];
    return out;
}

- (NSDictionary *)replayId:(NSData *)body {
    NSDictionary *req = jsonObject(body) ?: @{};
    BOOL found = NO;
    NSInteger track = trailingNumber([NSString stringWithFormat:@"%@", req[@"track_name"] ?: @""], &found);
    NSArray *hits = found ? [self ghostsFor:req[@"profile_id"] track:track] : @[];
    NSArray *chosen = nil;
    for (NSArray *h in hits) if (I(h[1][@"metadata"][@"drive_time"]) == I(req[@"drive_time"]) && req[@"drive_time"]) { chosen = h; break; }
    if (!chosen) chosen = hits.firstObject;
    NSInteger cid = chosen ? I(chosen[0]) : 0;
    [self note:cid ? [NSString stringWithFormat:@"   replay %ld for %@ %@ ms", (long)cid, req[@"track_name"], req[@"drive_time"]]
                   : [NSString stringWithFormat:@"   no ghost for %@", req[@"track_name"]]];
    return @{@"replay_id": @(cid)};
}

- (NSDictionary *)searchGhost:(TFRequest *)req {
    NSInteger track = [req param:@"track_id"] ? [[req param:@"track_id"] integerValue] : -1;
    NSMutableArray *contents = [NSMutableArray array];
    for (NSString *pid in [req listParam:@"players"]) {
        NSArray *hits = [self ghostsFor:pid track:track];
        if ([req param:@"drive_time"]) {
            NSInteger dt = [[req param:@"drive_time"] integerValue];
            NSArray *f = [hits filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSArray *h, id _) { return I(h[1][@"metadata"][@"drive_time"]) == dt; }]];
            if (f.count) hits = f;
        }
        if (hits.count) [contents addObject:@{@"contentId": hits[0][0], @"profileId": pid, @"metadata": hits[0][1][@"metadata"]}];
    }
    return @{@"contents": contents};
}

- (NSMutableDictionary *)parseMetadata:(NSData *)body {
    NSString *text = [[[NSString alloc] initWithData:body encoding:NSUTF8StringEncoding] ?: @""
                      stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSInteger open = [text componentsSeparatedByString:@"{"].count - 1, close = [text componentsSeparatedByString:@"}"].count - 1;
    for (NSInteger i = close; i < open; i++) text = [text stringByAppendingString:@"}"];
    NSDictionary *d = jsonObject([text dataUsingEncoding:NSUTF8StringEncoding]);
    if ([d isKindOfClass:NSDictionary.class]) return [d[@"metadata"] isKindOfClass:NSDictionary.class] ? [d[@"metadata"] mutableCopy] : [NSMutableDictionary dictionary];
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    NSRegularExpression *re = [NSRegularExpression regularExpressionWithPattern:@"\"(\\w+)\"\\s*:\\s*(-?\\d+)" options:0 error:nil];
    for (NSTextCheckingResult *m in [re matchesInString:text options:0 range:NSMakeRange(0, text.length)])
        out[[text substringWithRange:[m rangeAtIndex:1]]] = @([[text substringWithRange:[m rangeAtIndex:2]] integerValue]);
    return out;
}

- (NSNumber *)bestTime:(NSInteger)track {
    NSDictionary *st = _store[@"results"][[NSString stringWithFormat:@"track%ld", (long)track]][_profileId];
    return st ? st[@"drivetime"] : nil;
}

/// A ghost is stored only if it is the run behind the player's current best result for that leaderboard (the game
/// uploads only after "updated"; its resync path re-sends the same run). Without a result, accept unless a faster
/// ghost is held.
- (BOOL)acceptable:(NSInteger)track driveTime:(NSInteger)ms {
    NSNumber *best = [self bestTime:track];
    if (best) return I(best) == ms;
    for (NSArray *h in [self ghostsFor:_profileId track:track])
        if (I(h[1][@"track_id"]) == track) return ms <= (I(h[1][@"metadata"][@"drive_time"]) ?: (1L << 31));
    return YES;
}

- (TFResponse *)addGhost:(NSData *)body {
    NSMutableDictionary *meta = [self parseMetadata:body];
    NSInteger track = meta[@"track_id"] ? I(meta[@"track_id"]) : -1;
    if (I(meta[@"drive_time"]) && ![self acceptable:track driveTime:I(meta[@"drive_time"])]) {
        [self note:[NSString stringWithFormat:@"   refused ghost track %ld: %@ ms is not the current best (%@ ms)", (long)track, meta[@"drive_time"], [self bestTime:track]]];
        return [TFResponse json:@{@"errorCode": @409, @"message": @"not the current best run"} status:409];
    }
    NSInteger cid = [self newId];
    [_lock lock];
    _store[@"ghosts"][[@(cid) stringValue]] = [@{@"profile": _profileId, @"track_id": @(track), @"metadata": meta, @"payload": @NO} mutableCopy];
    [self saveStore];
    [_lock unlock];
    [self note:[NSString stringWithFormat:@"   new ghost content %ld for track %ld (%@ ms)", (long)cid, (long)track, meta[@"drive_time"]]];
    return [TFResponse json:@{@"contentId": @(cid), @"payloadUploadUrl": [NSString stringWithFormat:@"%@/public/userstorage/v2/content/ghost/%ld/payload", _base, (long)cid]}];
}

- (TFResponse *)putGhostPayload:(NSString *)cid body:(NSData *)body {
    [_lock lock];
    NSMutableDictionary *g = _store[@"ghosts"][cid];
    if (!g || ![g[@"profile"] isEqual:_profileId]) {
        [_lock unlock];
        return [TFResponse json:@{@"errorCode": @404, @"message": @"unknown content"} status:404];
    }
    NSNumber *ms = TFGhostDriveTime(body);
    if (ms && ![self acceptable:I(g[@"track_id"]) driveTime:I(ms)]) {
        [_lock unlock];
        [self note:[NSString stringWithFormat:@"   refused ghost payload for track %@: %@ ms is not the current best (%@ ms)", g[@"track_id"], ms, [self bestTime:I(g[@"track_id"])]]];
        return [TFResponse json:@{@"errorCode": @409, @"message": @"not the current best run"} status:409];
    }
    [body writeToFile:[self ghostPath:cid] atomically:YES];
    g[@"payload"] = @YES;
    g[@"metadata"][@"size"] = @(body.length);
    if (ms) g[@"metadata"][@"drive_time"] = ms;
    [g removeObjectForKey:@"source"];
    for (NSString *other in [_store[@"ghosts"] allKeys]) {  // keep one ghost per profile and leaderboard
        NSDictionary *o = _store[@"ghosts"][other];
        if (![other isEqual:cid] && [o[@"profile"] isEqual:g[@"profile"]] && I(o[@"track_id"]) == I(g[@"track_id"]))
            [_store[@"ghosts"] removeObjectForKey:other];
    }
    [self saveStore];
    [_lock unlock];
    [self note:[NSString stringWithFormat:@"   stored ghost %@: track %@, %lu bytes", cid, g[@"track_id"], (unsigned long)body.length]];
    return [TFResponse json:@{@"contentId": @(cid.integerValue)}];
}

- (TFResponse *)putGhostMetadata:(NSString *)cid body:(NSData *)body {
    [_lock lock];
    NSMutableDictionary *g = _store[@"ghosts"][cid];
    if (!g) {
        [_lock unlock];
        return [TFResponse json:@{@"errorCode": @404, @"message": @"unknown content"} status:404];
    }
    NSMutableDictionary *meta = [self parseMetadata:body];
    [meta removeObjectForKey:@"size"];
    [g[@"metadata"] addEntriesFromDictionary:meta];
    [self saveStore];
    [_lock unlock];
    return [TFResponse json:@{@"contentId": @(cid.integerValue)}];
}

- (NSString *)riderName:(NSString *)pid {
    if ([pid isEqual:_profileId]) {
        [self refreshName];
        return _name;
    }
    return _store[@"riders"][pid][@"name"] ?: @"rider";
}

- (NSDictionary *)session {
    [self refreshName];
    NSString *ticket = [self ticket];
    return @{@"platformType": @"uplay", @"ticket": ticket, @"profileId": _profileId, @"userId": _profileId,
             @"nameOnPlatform": _name, @"environment": @"Prod", @"expiration": isoTime([NSDate dateWithTimeIntervalSinceNow:3 * 3600]),
             @"serverTime": isoTime([NSDate date]), @"sessionId": TFUUID5(TFNamespaceOID, ticket)};
}

#pragma mark - routes

- (void)registerCoreRoutes:(TFRouter *)r {
    __weak TFServices *w = self;
    [r route:@"GET" path:@"/public/playerstats/v1/ranking/([^/]+)" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:[w leaderboard:c[0] request:q]];
    }];
    [r route:@"GET" path:@"/public/playerstats/v1/stats/([^/]+)" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:@{@"statboard": c[0], @"results": [w leaderboard:c[0] request:q][@"results"]}];
    }];
    [r route:@"POST" path:@"/public/playerstats/v1/stats/(global_stats(?:_donkey|_crazy)?)" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        BOOL changed = NO;
        for (NSDictionary *up in [w parseUpdates:q.body])
            if ([up isKindOfClass:NSDictionary.class]) changed |= [w submitGlobal:up board:c[0]];
        return [TFResponse json:@{@"result": @{@"updated": changed ? @1 : @0}}];
    }];
    [r route:@"POST" path:@"/public/resultservice/v1/enhancestats/batch_update" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        NSMutableArray *done = [NSMutableArray array];
        for (NSDictionary *up in [w parseUpdates:q.body]) {
            NSString *name = [up isKindOfClass:NSDictionary.class] ? up[@"track_name"] : nil;
            if (name.length) {
                [w submit:name update:up];
                [done addObject:@{@"track_name": name}];
            }
        }
        return [TFResponse json:@{@"status": done}];
    }];
    [r route:@"POST" path:@"/public/resultservice/v1/enhancestats/([^/]+)" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        BOOL improved = NO;
        for (NSDictionary *up in [w parseUpdates:q.body]) improved |= [w submit:c[0] update:up];
        return [TFResponse json:@{@"result": @{@"updated": improved ? @1 : @0}}];
    }];
    [r route:@"GET" path:@"/public/resultservice/v1/replaydata" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        if (![q param:@"track_id"]) return nil;
        NSInteger track = [[q param:@"track_id"] integerValue];
        for (NSArray *h in [w ghostsFor:w.profileId track:track])
            if (I(h[1][@"track_id"]) == track) return [TFResponse json:@{@"content_id": h[0]}];
        return [TFResponse json:@{@"content_id": @0}];
    }];
    [r route:@"POST" path:@"/public/resultservice/v1/replay_id" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:[w replayId:q.body]];
    }];
    [r route:@"GET" path:@"/public/userstorage/v2/search/ghost/get_ghost(?:_timed)?" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:[w searchGhost:q]];
    }];
    [r route:@"POST" path:@"/public/userstorage/v2/content/ghost" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [w addGhost:q.body];
    }];
    [r route:@"GET" path:@"/public/userstorage/v2/content/ghost/([0-9]+)/payload" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFServices *s = w;
        [s.lock lock];
        NSDictionary *g = s.store[@"ghosts"][c[0]];
        BOOL ok = g && (g[@"payload"] == nil || [g[@"payload"] boolValue]);
        [s.lock unlock];
        NSData *d = ok ? [NSData dataWithContentsOfFile:[s ghostPath:c[0]]] : nil;
        return d ? [TFResponse data:d] : nil;
    }];
    [r route:@"PUT" path:@"/public/userstorage/v2/content/ghost/([0-9]+)/payload" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [w putGhostPayload:c[0] body:q.body];
    }];
    [r route:@"PUT" path:@"/public/userstorage/v2/content/ghost/([0-9]+)" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [w putGhostMetadata:c[0] body:q.body];
    }];
    [r route:@"POST" path:@"/public/liveevents/v1/weekly_track_system/basic_info" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:@{}];  // outfit data: any 200 ends the game's 10x retry
    }];
    [r route:@"GET" path:@"/avatars/(?:([0-9a-fA-F-]{36})/default|fallback)_146_146\\.png" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFServices *s = w;
        NSString *file = [([c[0] length] ? c[0] : @"fallback") stringByAppendingString:@".png"];
        for (NSString *dir in @[s->_avatarsDir ?: @"", [s.dataDir stringByAppendingPathComponent:@"avatars"]]) {
            if (!dir.length) continue;
            NSData *d = [NSData dataWithContentsOfFile:[dir stringByAppendingPathComponent:file]];
            if (d) return [TFResponse data:d];
        }
        NSString *community = [c[0] length] ? s->_communityAvatars[c[0]] : nil;
        NSData *d = community ? [NSData dataWithContentsOfFile:community] : nil;
        return [TFResponse data:d ?: TFAvatarPNG([c[0] length] ? c[0] : @"fallback")];  // a helmet in the rider's colours
    }];
    [r route:@"GET" path:@"/v1/profiles" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        NSMutableArray *out = [NSMutableArray array];
        for (NSString *i in [q listParam:@"profileId"]) {
            if (!i.length) continue;
            [out addObject:@{@"profileId": i, @"userId": i, @"idOnPlatform": i, @"platformType": @"uplay", @"nameOnPlatform": [w riderName:i]}];
        }
        return [TFResponse json:@{@"profiles": out}];
    }];
    [r route:@"GET" path:@"/v1/profiles/([0-9a-fA-F-]{36})" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        // OnlineUbiservices::getPlayerProfile (robots): one profile object
        return [TFResponse json:@{@"profileId": c[0], @"userId": c[0], @"idOnPlatform": c[0], @"platformType": @"uplay",
                                  @"nameOnPlatform": [w riderName:c[0]]}];
    }];
    [r route:@"GET" path:@"/v1/applications/[^/]+/configuration" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        return [TFResponse json:@{@"configuration": @{@"sandboxes": @[@{@"name": kSandbox, @"friendlyName": kSandbox, @"url": w.base}]}}];
    }];
    [r route:@"GET" path:@"/profile/" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFResponse *resp = [TFResponse json:@{}];
        resp.headers = @{@"Server-Time": [NSString stringWithFormat:@"%.3f", NSDate.date.timeIntervalSince1970]};
        return resp;
    }];
    [r route:nil path:@"/v[12]/profiles/sessions" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        if (![q.method isEqualToString:@"POST"] && ![q.method isEqualToString:@"PUT"]) return nil;
        TFServices *s = w;
        [s note:[NSString stringWithFormat:@"   login request: %@; %@", tokenSummary(q), q.headers[@"user-agent"] ?: @"-"]];
        NSString *ua = q.headers[@"user-agent"] ?: @"";   // the game's: "<bundle id>;<name>;<version>;(...)"
        NSString *client = [ua containsString:@";"] ? [[[ua componentsSeparatedByString:@";"] firstObject]
                            stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet] : @"";
        if (s.appId.length && client.length && ![client isEqualToString:s.appId]) {
            // Another copy of the game (all use port 7979) reached this server because its own could not start. A login
            // here would give it this player's profile, and the game then parks its own progress as player_<hash>.prgstore
            // and starts a new player (ProgressSyncManager::switchLocalProgress).
            [s note:[NSString stringWithFormat:@"   login refused: %@ is another app; this server belongs to %@", client, s.appId]];
            return [TFResponse json:@{@"errorCode": @403, @"message": @"this local server belongs to another app"} status:403];
        }
        NSString *requested = requestedName(q);
        if (requested && !s->_fixedName) {
            [s.lock lock];
            s.store[@"player_name"] = requested;
            [s saveStore];
            [s.lock unlock];
            [s note:[NSString stringWithFormat:@"   name changed to %@", requested]];
        }
        NSDictionary *sess = [w session];
        [w note:[NSString stringWithFormat:@"   login as %@", sess[@"nameOnPlatform"]]];
        return [TFResponse json:sess];
    }];
}

- (void)registerQuietRoutes:(TFRouter *)r {
    // Requests the original services answered that have no local equivalent (yet): 404 = "nothing here", which the
    // game treats like an unreachable service. Feature modules register before this.
    [r route:nil path:@"/public/(?:targeting|pvp_matches|gift|match|liveevents)/.*" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFResponse *resp = [TFResponse json:@{@"errorCode": @404, @"message": @"not offered by the local server"} status:404];
        resp.tag = @"not offered";
        return resp;
    }];
}
@end
