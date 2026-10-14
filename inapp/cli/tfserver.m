// macOS command-line build of the in-app local services (for tests and development; same options as
// server/local_services.py where they overlap).
// Usage: tfserver [--container <app container Data dir>] [--documents <dir>] [--data <dir>] [--port 7979]
//                 [--profile-id <uuid>] [--name <name>] [--avatars <dir>] [--log <file>]
//                 [--community <layer dir>] [--app-id <bundle id>]
#import <Foundation/Foundation.h>
#import "TFLocalServices.h"

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSMutableDictionary *o = [NSMutableDictionary dictionary];
        for (int i = 1; i + 1 < argc; i += 2) o[@(argv[i])] = @(argv[i + 1]);
        NSString *container = o[@"--container"] ?: [NSHomeDirectory() stringByAppendingPathComponent:
                                                    @"Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data"];
        TFLocalServicesConfig *c = [TFLocalServicesConfig new];
        c.documentsDir = o[@"--documents"] ?: [container stringByAppendingPathComponent:@"Documents"];
        c.dataDir = o[@"--data"] ?: [c.documentsDir stringByAppendingPathComponent:@"LocalServices"];
        c.port = (uint16_t)[o[@"--port"] ?: @"7979" intValue];
        c.avatarsDir = o[@"--avatars"];
        c.communityDir = o[@"--community"];
        c.profileId = o[@"--profile-id"];
        c.name = o[@"--name"];
        c.appId = o[@"--app-id"];
        [NSFileManager.defaultManager createDirectoryAtPath:c.dataDir withIntermediateDirectories:YES attributes:nil error:nil];
        NSFileHandle *logFile = nil;
        if (o[@"--log"]) {
            NSString *p = o[@"--log"];
            if (![NSFileManager.defaultManager fileExistsAtPath:p]) [NSFileManager.defaultManager createFileAtPath:p contents:nil attributes:nil];
            logFile = [NSFileHandle fileHandleForWritingAtPath:p];
            [logFile seekToEndOfFile];
        }
        NSDateFormatter *f = [NSDateFormatter new];
        f.dateFormat = @"HH:mm:ss ";
        NSLock *lock = [NSLock new];
        c.log = ^(NSString *line) {
            NSString *s = [[f stringFromDate:NSDate.date] stringByAppendingFormat:@"%@\n", line];
            [lock lock];
            fputs(s.UTF8String, stdout);
            fflush(stdout);
            [logFile writeData:[s dataUsingEncoding:NSUTF8StringEncoding]];
            [lock unlock];
        };
        NSError *err = nil;
        if (!TFLocalServicesStart(c, &err)) {
            fprintf(stderr, "cannot listen on 127.0.0.1:%u: %s\n", c.port, err.localizedDescription.UTF8String);
            return 1;
        }
        dispatch_main();
    }
}
