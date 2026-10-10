// Robots: "live opponents" for the A.N.B.A. quest line (RobotmanManager / OnlineRobotMission) and mission ghosts.
// Same behaviour as the robot part of server/local_services.py:
//   GET match/v1/robot?track_name=track<N>&range=&offset=   -> {player, drivetime, upgrades, data, score_value, replay_id}
//   GET match/v1/robot_v2?track_name=&score=&range=          -> the same, near a target score
//   GET resultservice/v1/robot_replaydata?track_id=&time=&player= -> that rider's ghost bytes
// Opponents come from the store's ghosts: other riders first (exact leaderboard, else same base track), the
// player's own only if there is no one else; the closest one just slower than the player's best, faster ones after
// that, the slowest when the player has no time. No ghost -> 404, and the game moves on to another track.
#import "TFServices.h"

static NSInteger I(id v) { return [v respondsToSelector:@selector(longLongValue)] ? (NSInteger)[v longLongValue] : 0; }

@interface TFRobots : NSObject <TFServiceModule>
@end

@implementation TFRobots

static NSArray *candidates(TFServices *s, NSInteger track) {
    NSMutableArray *others = [NSMutableArray array], *own = [NSMutableArray array];
    [s.lock lock];
    NSArray *ids = [[s.store[@"ghosts"] allKeys] sortedArrayUsingComparator:^NSComparisonResult(NSString *a, NSString *b) {
        return [@(a.integerValue) compare:@(b.integerValue)];
    }];
    for (NSString *cid in ids) {
        NSDictionary *g = s.store[@"ghosts"][cid];
        NSInteger t = I(g[@"track_id"]);
        if ((g[@"payload"] && ![g[@"payload"] boolValue]) || !(t == track || (t & 0xFFFF) == track)) continue;
        NSArray *e = @[g[@"profile"] ?: @"", @(cid.integerValue), g, @(I(g[@"metadata"][@"drive_time"]))];
        [([g[@"profile"] isEqual:s.profileId] ? own : others) addObject:e];
    }
    [s.lock unlock];
    NSPredicate *exactP = [NSPredicate predicateWithBlock:^BOOL(NSArray *e, id _) { return I(e[2][@"track_id"]) == track; }];
    NSArray *exact = [others filteredArrayUsingPredicate:exactP];
    if (exact.count) return exact;
    if (others.count) return others;
    NSArray *ownExact = [own filteredArrayUsingPredicate:exactP];
    return ownExact.count ? ownExact : own;
}

static NSArray *pick(TFServices *s, NSInteger track, NSNumber *target, NSInteger offset) {
    NSArray *c = [candidates(s, track) filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSArray *e, id _) { return I(e[3]) > 0; }]];
    if (!c.count) return nil;
    if (!target) {
        [s.lock lock];
        NSDictionary *best = s.store[@"results"][[NSString stringWithFormat:@"track%ld", (long)track]][s.profileId];
        [s.lock unlock];
        if (best) target = best[@"drivetime"];
    }
    NSArray *order;
    if (!target) {
        order = [c sortedArrayUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
            if (I(a[3]) != I(b[3])) return I(a[3]) > I(b[3]) ? NSOrderedAscending : NSOrderedDescending;
            return [a[1] compare:b[1]];
        }];
    } else {
        NSInteger t = I(target);
        NSArray *slower = [[c filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSArray *e, id _) { return I(e[3]) >= t; }]]
            sortedArrayUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
                if (I(a[3]) != I(b[3])) return I(a[3]) < I(b[3]) ? NSOrderedAscending : NSOrderedDescending;
                return [a[1] compare:b[1]];
            }];
        NSArray *faster = [[c filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSArray *e, id _) { return I(e[3]) < t; }]]
            sortedArrayUsingComparator:^NSComparisonResult(NSArray *a, NSArray *b) {
                if (I(a[3]) != I(b[3])) return I(a[3]) > I(b[3]) ? NSOrderedAscending : NSOrderedDescending;
                return [a[1] compare:b[1]];
            }];
        order = [slower arrayByAddingObjectsFromArray:faster];
    }
    NSInteger i = ((offset % (NSInteger)order.count) + (NSInteger)order.count) % (NSInteger)order.count;
    return order[i];
}

static NSDictionary *reply(TFServices *s, NSArray *p) {
    NSString *rider = p[0];
    NSDictionary *g = p[2];
    NSInteger ms = I(p[3]);
    [s.lock lock];
    NSDictionary *st = s.store[@"results"][[NSString stringWithFormat:@"track%@", g[@"track_id"]]][rider] ?: @{};
    [s.lock unlock];
    NSInteger data = I(st[@"data"]);
    return @{@"player": rider, @"drivetime": @(ms), @"upgrades": st[@"upgrades"] ?: @0, @"data": @(data),
             @"score_value": st[@"score_value"] ?: @(360000000 - ms - (data & 0xFF) * 3600000), @"replay_id": p[1]};
}

static NSInteger trackOf(NSString *name, BOOL *ok) {
    NSRange r = [name ?: @"" rangeOfString:@"[0-9]+$" options:NSRegularExpressionSearch];
    *ok = r.location != NSNotFound;
    return *ok ? [[name substringWithRange:r] integerValue] : 0;
}

+ (void)registerWithServices:(TFServices *)services router:(TFRouter *)router {
    __weak TFServices *w = services;
    [router route:@"GET" path:@"/public/match/v1/robot" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFServices *s = w;
        BOOL ok;
        NSInteger track = trackOf([q param:@"track_name"], &ok);
        if (!ok) return nil;
        NSArray *p = pick(s, track, nil, [[q param:@"offset"] integerValue]);
        if (!p) {
            [s note:[NSString stringWithFormat:@"   no robot opponent for track %ld", (long)track]];
            return nil;
        }
        [s note:[NSString stringWithFormat:@"   robot for track %ld: %@ %@ ms (content %@)", (long)track, [s riderName:p[0]], p[3], p[1]]];
        return [TFResponse json:reply(s, p)];
    }];
    [router route:@"GET" path:@"/public/match/v1/robot_v2" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFServices *s = w;
        BOOL ok;
        NSInteger track = trackOf([q param:@"track_name"], &ok);
        if (!ok) return nil;
        NSInteger score = [[q param:@"score"] integerValue];
        NSNumber *target = score > 0 && score <= 360000000 ? @(360000000 - score) : nil;
        NSArray *p = pick(s, track, target, 0);
        if (!p) {
            [s note:[NSString stringWithFormat:@"   no mission ghost for track %ld", (long)track]];
            return nil;
        }
        [s note:[NSString stringWithFormat:@"   mission ghost for track %ld (score %ld): %@ %@ ms", (long)track, (long)score, [s riderName:p[0]], p[3]]];
        return [TFResponse json:reply(s, p)];
    }];
    [router route:@"GET" path:@"/public/resultservice/v1/robot_replaydata" handler:^TFResponse *(TFRequest *q, NSArray *c) {
        TFServices *s = w;
        NSInteger track = [q param:@"track_id"] ? [[q param:@"track_id"] integerValue] : -1;
        NSArray *hits = [s ghostsFor:[q param:@"player"] ?: @"" track:track];
        if ([q param:@"time"]) {
            NSInteger t = [[q param:@"time"] integerValue];
            NSArray *f = [hits filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSArray *h, id _) {
                return I(h[1][@"metadata"][@"drive_time"]) == t;
            }]];
            if (f.count) hits = f;
        }
        NSData *d = hits.count ? [NSData dataWithContentsOfFile:[s ghostPath:hits[0][0]]] : nil;
        return d ? [TFResponse data:d] : nil;
    }];
}
@end
