#import "TFLocalServices.h"
#import "TFHTTP.h"
#import "TFServices.h"

@implementation TFLocalServicesConfig
@end

NSArray<Class> *TFLocalServicesModules(void) {
    return @[NSClassFromString(@"TFRobots")];  // robots / live opponents (TFRobots.m)
}

/// Router whose dispatch waits until the store is loaded.
@interface TFGatedRouter : TFRouter
@property(nonatomic, strong) dispatch_group_t ready;
@property(nonatomic, copy) NSString *_Nullable (^probe)(void);
@property(nonatomic, copy) void (^log)(NSString *);
@property(nonatomic, copy) NSString *lastProbe;
@end
@implementation TFGatedRouter
- (TFResponse *)dispatch:(TFRequest *)request {
    dispatch_group_wait(self.ready, dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_SEC));
    if (self.probe) {
        NSString *state = self.probe();
        @synchronized(self) {
            if (state && ![state isEqualToString:self.lastProbe]) {
                self.lastProbe = state;
                self.log([@"   game: " stringByAppendingString:state]);
            }
        }
    }
    return [super dispatch:request];
}
@end

BOOL TFLocalServicesStart(TFLocalServicesConfig *config, NSError **error) {
    void (^log)(NSString *) = config.log ?: ^(NSString *line) {};
    TFServices *services = [[TFServices alloc] initWithDocuments:config.documentsDir dataDir:config.dataDir port:config.port
                                                       profileId:config.profileId name:config.name avatarsDir:config.avatarsDir log:log];
    TFGatedRouter *router = [TFGatedRouter new];
    router.ready = dispatch_group_create();
    router.probe = config.probe;
    router.log = log;
    [services registerCoreRoutes:router];
    for (Class module in TFLocalServicesModules()) [module registerWithServices:services router:router];
    [services registerQuietRoutes:router];

    dispatch_group_enter(router.ready);
    TFHTTPServer *server = [[TFHTTPServer alloc] initWithPort:config.port router:router log:log];
    if (![server start:error]) {
        dispatch_group_leave(router.ready);
        return NO;
    }
    static NSMutableArray *keep;  // the server lives for the process
    keep = keep ?: [NSMutableArray array];
    [keep addObject:server];
    [keep addObject:services];  // route handlers hold it weakly
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        [services loadStore:config.communityDir];
        log([NSString stringWithFormat:@"listening on %@ for %@ (%@); documents %@", services.base, services.name,
             services.profileId, config.documentsDir]);
        dispatch_group_leave(router.ready);
    });
    return YES;
}
