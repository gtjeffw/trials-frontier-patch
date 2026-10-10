// In-app entry point: libTFLocalServices.dylib is loaded by the game (an LC_LOAD_DYLIB added by the patch) and starts
// the local services before the game's first request. Data lives in Documents/LocalServices (never purged, included
// in device backups); a store left in Library/LocalServices by the development server is moved there once.
#import <Foundation/Foundation.h>
#import <mach-o/dyld.h>
#import <mach-o/loader.h>
#import <string.h>
#import "TFLocalServices.h"

// TrialsFrontier 7.9.0 arm64 (the executable the patches target): where the game keeps its player record.
static const uint8_t kGameUUID[16] = {0xD1, 0xB9, 0xB8, 0x83, 0xE3, 0x09, 0x3B, 0x03, 0xA4, 0xC7, 0x96, 0x38, 0xF6, 0x62, 0x1A, 0x0E};
static const uint64_t kPlayerPointer = 0x100f2ed90;  // tr::GlobalData::m_player (unslid)

static BOOL knownGame(void) {
    const struct mach_header_64 *h = (const struct mach_header_64 *)_dyld_get_image_header(0);
    if (!h || h->magic != MH_MAGIC_64) return NO;
    const uint8_t *p = (const uint8_t *)(h + 1);
    for (uint32_t i = 0; i < h->ncmds; i++) {
        const struct load_command *lc = (const struct load_command *)p;
        if (lc->cmd == LC_UUID) return memcmp(((const struct uuid_command *)lc)->uuid, kGameUUID, 16) == 0;
        p += lc->cmdsize;
    }
    return NO;
}

static NSString *field(const char *base, size_t offset, size_t max) {
    return [[NSString alloc] initWithBytes:base + offset length:strnlen(base + offset, max) encoding:NSUTF8StringEncoding] ?: @"?";
}

/// The player's name fields as the game holds them: Player+0x10 (shown name), the chosen (silent-login) name
/// (OnlineData at +0x6be0, name at +0x168), Player+0x110 (profile id).
static NSString *gameState(void) {
    const char *player = *(const char *const *)(uintptr_t)(kPlayerPointer + _dyld_get_image_vmaddr_slide(0));
    if (!player) return @"(player not loaded)";
    return [NSString stringWithFormat:@"name '%@', chosen '%@', profile %@", field(player, 0x10, 128),
            field(player, 0x6be0 + 0x168, 64), field(player, 0x110, 40)];
}

static NSFileHandle *logHandle(NSString *path) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSDictionary *attrs = [fm attributesOfItemAtPath:path error:nil];
    if ([attrs fileSize] > 2 * 1024 * 1024) [fm moveItemAtPath:path toPath:[path stringByAppendingString:@".1"] error:nil];
    if (![fm fileExistsAtPath:path]) [fm createFileAtPath:path contents:nil attributes:nil];
    NSFileHandle *h = [NSFileHandle fileHandleForWritingAtPath:path];
    [h seekToEndOfFile];
    return h;
}

__attribute__((constructor)) static void TFLocalServicesBoot(void) {
    @autoreleasepool {
        NSFileManager *fm = NSFileManager.defaultManager;
        NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        NSString *lib = NSSearchPathForDirectoriesInDomains(NSLibraryDirectory, NSUserDomainMask, YES).firstObject;
        NSString *data = [docs stringByAppendingPathComponent:@"LocalServices"];
        NSString *old = [lib stringByAppendingPathComponent:@"LocalServices"];
        if (![fm fileExistsAtPath:data] && [fm fileExistsAtPath:old]) [fm moveItemAtPath:old toPath:data error:nil];
        [fm createDirectoryAtPath:data withIntermediateDirectories:YES attributes:nil error:nil];

        NSFileHandle *h = logHandle([data stringByAppendingPathComponent:@"server.log"]);
        NSDateFormatter *f = [NSDateFormatter new];
        f.dateFormat = @"yyyy-MM-dd HH:mm:ss ";
        NSLock *lock = [NSLock new];
        TFLocalServicesConfig *c = [TFLocalServicesConfig new];
        c.documentsDir = docs;
        c.dataDir = data;
        c.port = 7979;
        NSString *res = [[NSBundle.mainBundle resourcePath] stringByAppendingPathComponent:@"LocalServices"];
        // community layer: the one installed into the data (scripts/community.py install, updatable), else the one
        // built into the app (build.py --community)
        NSString *installed = [data stringByAppendingPathComponent:@"community"];
        NSString *builtIn = [res stringByAppendingPathComponent:@"community"];
        c.communityDir = [fm fileExistsAtPath:[installed stringByAppendingPathComponent:@"community.json"]] ? installed : builtIn;
        c.avatarsDir = [res stringByAppendingPathComponent:@"avatars"];
        if (knownGame()) c.probe = ^NSString *{ return gameState(); };
        c.log = ^(NSString *line) {
            [lock lock];
            [h writeData:[[[f stringFromDate:NSDate.date] stringByAppendingFormat:@"%@\n", line] dataUsingEncoding:NSUTF8StringEncoding]];
            [lock unlock];
        };
        NSError *err = nil;
        if (!TFLocalServicesStart(c, &err)) c.log([NSString stringWithFormat:@"could not listen on 127.0.0.1:7979: %@", err]);
    }
}
