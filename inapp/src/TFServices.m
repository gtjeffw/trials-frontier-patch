#import "TFServices.h"
#import "TFSave.h"

static NSString *const kSandbox = @"triag_ip_lnch61_a_ws";

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
    NSString *_ticket;
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
        if (!profileId.length || !name.length) {
            NSString *n = nil, *p = nil;
            TFReadProfile([self saveRaw] ?: [NSData data], &n, &p);
            if (!profileId.length) profileId = p;
            if (!name.length) name = n;
        }
        _profileId = [profileId copy] ?: @"";
        _name = [name copy] ?: @"";
        _ticket = [@"local-" stringByAppendingString:[TFUUID5(TFNamespaceURL, _profileId) stringByReplacingOccurrencesOfString:@"-" withString:@""]];
    }
    return self;
}

- (void)note:(NSString *)line { _log(line); }

- (NSString *)documents:(NSString *)name { return [_documentsDir stringByAppendingPathComponent:name]; }

- (NSData *)saveRaw {
    NSData *f = [NSData dataWithContentsOfFile:[self documents:@"player.bin"]];
    return f ? TFDecodeSave(f) : nil;
}

- (NSDictionary *)scores { return TFReadScores([self saveRaw] ?: [NSData data]); }

#pragma mark - store

- (void)loadStore {
    [_lock lock];
    NSFileManager *fm = NSFileManager.defaultManager;
    [fm createDirectoryAtPath:[_dataDir stringByAppendingPathComponent:@"ghosts"] withIntermediateDirectories:YES attributes:nil error:nil];
    NSMutableDictionary *s = jsonObject([NSData dataWithContentsOfFile:[_dataDir stringByAppendingPathComponent:@"store.json"]]);
    _store = s ?: [@{@"results": [NSMutableDictionary dictionary], @"ghosts": [NSMutableDictionary dictionary], @"next_id": @1000} mutableCopy];
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
    [self saveStore];
    NSInteger results = 0;
    for (NSDictionary *b in [_store[@"results"] allValues]) results += b.count;
    [self note:[NSString stringWithFormat:@"store %@: %ld results, %lu ghosts, %lu other riders (%ld imported now)", _dataDir,
                (long)results, (unsigned long)[_store[@"ghosts"] count], (unsigned long)[_store[@"riders"] count], (long)seeded]];
    [_lock unlock];
}

- (void)saveStore {
    [_lock lock];
    NSData *d = [NSJSONSerialization dataWithJSONObject:_store options:NSJSONWritingPrettyPrinted | NSJSONWritingWithoutEscapingSlashes error:nil];
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

- (void)importWorldRecords:(NSString *)wrPath ids:(NSString *)idsPath {
    [_lock lock];
    if (_store[@"world_records_imported"]) { [_lock unlock]; return; }
    NSDictionary *wr = jsonObject([NSData dataWithContentsOfFile:wrPath]);
    NSString *idsText = [NSString stringWithContentsOfFile:idsPath encoding:NSUTF8StringEncoding error:nil] ?: @"";
    NSRegularExpression *comments = [NSRegularExpression regularExpressionWithPattern:@"^\\s*//.*$" options:NSRegularExpressionAnchorsMatchLines error:nil];
    idsText = [comments stringByReplacingMatchesInString:idsText options:0 range:NSMakeRange(0, idsText.length) withTemplate:@""];
    NSMutableDictionary *site = [NSMutableDictionary dictionary];
    for (NSDictionary *e in jsonObject([idsText dataUsingEncoding:NSUTF8StringEncoding])) site[@(I(e[@"id"]))] = e[@"oid"];
    NSDictionary *flags = @{@"n": @0, @"d": @0x10000, @"c": @0x100000};
    NSInteger count = 0;
    for (NSString *sid in wr[@"tracks"]) {
        NSNumber *oid = site[@(sid.integerValue)];
        if (!oid) continue;
        NSDictionary *plats = wr[@"tracks"][sid];
        for (NSString *plat in plats) {
            if (![plat isEqualToString:@"a"] && ![plat isEqualToString:@"i"]) continue;
            NSDictionary *cats = plats[plat];
            for (NSString *cat in cats) {
                NSDictionary *e = cats[cat];
                if (![e isKindOfClass:NSDictionary.class] || !flags[cat]) continue;
                NSString *name = wr[@"riders"][I(e[@"r"])];
                NSString *rid = TFUUID5(TFNamespaceURL, [@"trialstrackmap-rider:" stringByAppendingString:name]);
                [self addRider:rid name:name source:@"wr2019"];
                count += [self addResult:[NSString stringWithFormat:@"track%ld", (long)(I(oid) | I(flags[cat]))] rider:rid
                                  faults:I(e[@"f"]) ms:I(e[@"t"]) bike:I(e[@"b"]) source:@"wr2019"];
            }
        }
    }
    _store[@"world_records_imported"] = wrPath.lastPathComponent;
    [self saveStore];
    [_lock unlock];
    [self note:[NSString stringWithFormat:@"world records %@: %ld results added", wrPath.lastPathComponent, (long)count]];
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
    NSArray *pids = [board.allKeys sortedArrayUsingComparator:^NSComparisonResult(NSString *a, NSString *b) {
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
    if ([pid isEqual:_profileId]) return _name;
    return _store[@"riders"][pid][@"name"] ?: @"rider";
}

- (NSDictionary *)session {
    return @{@"platformType": @"uplay", @"ticket": _ticket, @"profileId": _profileId, @"userId": _profileId,
             @"nameOnPlatform": _name, @"environment": @"Prod", @"expiration": isoTime([NSDate dateWithTimeIntervalSinceNow:3 * 3600]),
             @"serverTime": isoTime([NSDate date]), @"sessionId": TFUUID5(TFNamespaceOID, _ticket)};
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
        return nil;
    }];
    [r route:@"GET" path:@"/v1/profiles" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        NSMutableArray *out = [NSMutableArray array];
        for (NSString *i in [q listParam:@"profileId"]) {
            if (!i.length) continue;
            [out addObject:@{@"profileId": i, @"userId": i, @"idOnPlatform": i, @"platformType": @"uplay", @"nameOnPlatform": [w riderName:i]}];
        }
        return [TFResponse json:@{@"profiles": out}];
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
        return [TFResponse json:[w session]];
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
