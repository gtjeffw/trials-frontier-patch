// Local game services: the store (results, ghosts, other riders) and the core routes. Native port of
// server/local_services.py; both share the same HTTP API and on-disk store format (store.json + ghosts/ + avatars/).
//
// Extension point: a feature module (e.g. a daily robot challenge serving match/v1/robot and
// resultservice/v1/robot_replaydata from the stored riders' ghosts) implements TFServiceModule and is listed in
// TFLocalServicesModules() (TFLocalServices.m). Modules register their routes after the core and before the
// catch-all "not offered" route, and can use the store helpers below.
#import <Foundation/Foundation.h>
#import "TFHTTP.h"

NS_ASSUME_NONNULL_BEGIN

@interface TFServices : NSObject
@property(nonatomic, readonly, copy) NSString *profileId;
@property(nonatomic, readonly, copy) NSString *name;
@property(nonatomic, copy, nullable) NSString *appId;   // the game copy this server belongs to (bundle id)
@property(nonatomic, readonly, copy) NSString *base;          // http://127.0.0.1:<port>
@property(nonatomic, readonly, copy) NSString *documentsDir;  // the game's Documents (player.bin, ghost files)
@property(nonatomic, readonly, copy) NSString *dataDir;       // store directory
@property(nonatomic, readonly, strong) NSMutableDictionary *store;
@property(nonatomic, readonly, strong) NSRecursiveLock *lock;

- (instancetype)initWithDocuments:(NSString *)documentsDir dataDir:(NSString *)dataDir port:(uint16_t)port
                        profileId:(nullable NSString *)profileId name:(nullable NSString *)name
                       avatarsDir:(nullable NSString *)avatarsDir log:(void (^)(NSString *line))log;
- (void)note:(NSString *)line;

/// Load store.json (if any) and import what is new: own results and ghosts from the save, downloaded opponents; then
/// overlay the community layer (communityDir, default <dataDir>/community; never written into store.json).
- (void)loadStore:(nullable NSString *)communityDir;
- (void)saveStore;

// Store helpers for modules.
- (NSInteger)newId;
- (NSString *)ghostPath:(id)contentId;
- (void)addRider:(NSString *)riderId name:(NSString *)name source:(NSString *)source hash:(nullable NSString *)h;
- (BOOL)addResult:(NSString *)board rider:(NSString *)riderId faults:(NSInteger)faults ms:(NSInteger)ms
             bike:(NSInteger)bike source:(NSString *)source;
/// (content id, ghost entry) pairs of a profile on a leaderboard (exact id first, then same base track), fastest first.
- (NSArray<NSArray *> *)ghostsFor:(nullable NSString *)profile track:(NSInteger)track;
- (NSString *)riderName:(NSString *)profileId;

- (void)registerCoreRoutes:(TFRouter *)router;
- (void)registerQuietRoutes:(TFRouter *)router;
@end

@protocol TFServiceModule <NSObject>
+ (void)registerWithServices:(TFServices *)services router:(TFRouter *)router;
@end

NS_ASSUME_NONNULL_END
