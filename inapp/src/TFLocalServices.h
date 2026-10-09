// Start the local game services: used by the in-app entry point (TFEntry.m) and the macOS test tool (cli/tfserver.m).
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface TFLocalServicesConfig : NSObject
@property(nonatomic, copy) NSString *documentsDir;               // the game's Documents (player.bin, ghost files)
@property(nonatomic, copy) NSString *dataDir;                    // store directory
@property(nonatomic) uint16_t port;                              // 7979 (patched into the game)
@property(nonatomic, copy, nullable) NSString *avatarsDir;       // extra avatars (<profileId>.png), optional
@property(nonatomic, copy, nullable) NSString *worldRecords;     // wrrider.json, optional
@property(nonatomic, copy, nullable) NSString *worldRecordIds;   // ids.json, optional
@property(nonatomic, copy, nullable) NSString *profileId;        // default: from player.bin
@property(nonatomic, copy, nullable) NSString *name;             // default: from player.bin
@property(nonatomic, copy, nullable) void (^log)(NSString *line);
@end

/// Starts listening on 127.0.0.1:port at once; requests wait until the store is loaded (done on a background thread,
/// first run imports the save, its ghosts and downloaded opponents). Returns NO if the port is taken.
BOOL TFLocalServicesStart(TFLocalServicesConfig *config, NSError **error);

/// Feature modules (classes conforming to TFServiceModule), registered after the core routes. Add new ones here,
/// e.g. a daily robot challenge module.
NSArray<Class> *TFLocalServicesModules(void);

NS_ASSUME_NONNULL_END
