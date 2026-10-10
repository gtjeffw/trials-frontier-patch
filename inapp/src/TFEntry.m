// In-app entry point: libTFLocalServices.dylib is loaded by the game (an LC_LOAD_DYLIB added by the patch) and starts
// the local services before the game's first request. Data lives in Documents/LocalServices (never purged, included
// in device backups); a store left in Library/LocalServices by the development server is moved there once.
#import <Foundation/Foundation.h>
#import "TFLocalServices.h"

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
        c.log = ^(NSString *line) {
            [lock lock];
            [h writeData:[[[f stringFromDate:NSDate.date] stringByAppendingFormat:@"%@\n", line] dataUsingEncoding:NSUTF8StringEncoding]];
            [lock unlock];
        };
        NSError *err = nil;
        if (!TFLocalServicesStart(c, &err)) c.log([NSString stringWithFormat:@"could not listen on 127.0.0.1:7979: %@", err]);
    }
}
