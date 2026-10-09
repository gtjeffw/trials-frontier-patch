#import "TFHTTP.h"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

@implementation TFRequest
- (NSString *)param:(NSString *)name { return self.query[name].firstObject; }
- (NSArray<NSString *> *)listParam:(NSString *)name {
    NSArray *v = self.query[name];
    return v ? [[v componentsJoinedByString:@","] componentsSeparatedByString:@","] : @[];
}
@end

@implementation TFResponse
+ (instancetype)json:(id)object status:(NSInteger)status {
    TFResponse *r = [TFResponse new];
    r.status = status;
    r.json = object;
    r.headers = @{};
    return r;
}
+ (instancetype)json:(id)object { return [self json:object status:200]; }
+ (instancetype)data:(NSData *)data {
    TFResponse *r = [TFResponse new];
    r.status = 200;
    r.data = data;
    r.headers = @{};
    return r;
}
- (NSData *)bodyBytes {
    if (self.data) return self.data;
    // Compact JSON: the mobile login library strstr()s for "environment":"Prod" and "nameOnPlatform":".
    return [NSJSONSerialization dataWithJSONObject:self.json ?: @{} options:NSJSONWritingWithoutEscapingSlashes error:nil];
}
- (NSString *)contentType {
    if (!self.data) return @"application/json";
    return self.data.length >= 4 && memcmp(self.data.bytes, "\x89PNG", 4) == 0 ? @"image/png" : @"application/octet-stream";
}
@end

@interface TFRoute : NSObject
@property(nonatomic, copy, nullable) NSString *method;
@property(nonatomic, strong) NSRegularExpression *regex;
@property(nonatomic, copy) TFHandler handler;
@end
@implementation TFRoute
@end

@implementation TFRouter {
    NSMutableArray<TFRoute *> *_routes;
}
- (instancetype)init {
    if ((self = [super init])) _routes = [NSMutableArray array];
    return self;
}
- (void)route:(NSString *)method path:(NSString *)pattern handler:(TFHandler)handler {
    TFRoute *r = [TFRoute new];
    r.method = method;
    r.regex = [NSRegularExpression regularExpressionWithPattern:[NSString stringWithFormat:@"^(?:%@)$", pattern] options:0 error:nil];
    r.handler = handler;
    [_routes addObject:r];
}
- (TFResponse *)dispatch:(TFRequest *)request {
    for (TFRoute *r in _routes) {
        if (r.method && ![r.method isEqualToString:request.method]) continue;
        NSTextCheckingResult *m = [r.regex firstMatchInString:request.path options:0 range:NSMakeRange(0, request.path.length)];
        if (!m) continue;
        NSMutableArray *caps = [NSMutableArray array];
        for (NSUInteger i = 1; i < m.numberOfRanges; i++) {
            NSRange g = [m rangeAtIndex:i];
            [caps addObject:g.location == NSNotFound ? @"" : [request.path substringWithRange:g]];
        }
        TFResponse *resp = r.handler(request, caps);
        if (resp) return resp;
    }
    return nil;
}
@end

static NSString *percentDecode(NSString *s) {
    return [[s stringByReplacingOccurrencesOfString:@"+" withString:@" "] stringByRemovingPercentEncoding] ?: s;
}

static NSDictionary *parseQuery(NSString *q) {
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    for (NSString *pair in [q componentsSeparatedByCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@"&;"]]) {
        NSRange eq = [pair rangeOfString:@"="];
        if (eq.location == NSNotFound) continue;
        NSString *k = percentDecode([pair substringToIndex:eq.location]);
        NSString *v = percentDecode([pair substringFromIndex:eq.location + 1]);
        if (v.length == 0) continue;  // parse_qs drops blank values
        NSMutableArray *a = out[k] ?: (out[k] = [NSMutableArray array]);
        [a addObject:v];
    }
    return out;
}

@implementation TFHTTPServer {
    uint16_t _port;
    TFRouter *_router;
    void (^_log)(NSString *);
    int _fd;
}

- (instancetype)initWithPort:(uint16_t)port router:(TFRouter *)router log:(void (^)(NSString *))log {
    if ((self = [super init])) {
        _port = port;
        _router = router;
        _log = log;
        _fd = -1;
    }
    return self;
}

- (BOOL)start:(NSError **)error {
    _fd = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in a = {0};
    a.sin_len = sizeof a;
    a.sin_family = AF_INET;
    a.sin_port = htons(_port);
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(_fd, (struct sockaddr *)&a, sizeof a) != 0 || listen(_fd, 16) != 0) {
        if (error) *error = [NSError errorWithDomain:NSPOSIXErrorDomain code:errno userInfo:nil];
        close(_fd);
        _fd = -1;
        return NO;
    }
    NSThread *t = [[NSThread alloc] initWithTarget:self selector:@selector(acceptLoop) object:nil];
    t.name = @"TFLocalServices.accept";
    [t start];
    return YES;
}

- (void)acceptLoop {
    for (;;) {
        int c = accept(_fd, NULL, NULL);
        if (c < 0) continue;
        struct timeval tv = {60, 0};
        setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
        int one = 1;
        setsockopt(c, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
        [NSThread detachNewThreadWithBlock:^{ [self serve:c]; }];
    }
}

static BOOL writeAll(int fd, NSData *d) {
    const uint8_t *p = d.bytes;
    NSUInteger left = d.length;
    while (left) {
        ssize_t n = write(fd, p, left);
        if (n <= 0) return NO;
        p += n;
        left -= (NSUInteger)n;
    }
    return YES;
}

- (void)serve:(int)fd {
    NSMutableData *buf = [NSMutableData data];
    uint8_t chunk[16384];
    for (;;) {
        @autoreleasepool {
            NSRange end;
            while ((end = [buf rangeOfData:[@"\r\n\r\n" dataUsingEncoding:NSASCIIStringEncoding] options:0
                                     range:NSMakeRange(0, buf.length)]).location == NSNotFound) {
                ssize_t n = read(fd, chunk, sizeof chunk);
                if (n <= 0) { close(fd); return; }
                [buf appendBytes:chunk length:(NSUInteger)n];
            }
            NSString *head = [[NSString alloc] initWithData:[buf subdataWithRange:NSMakeRange(0, end.location)]
                                                   encoding:NSISOLatin1StringEncoding];
            NSArray<NSString *> *lines = [head componentsSeparatedByString:@"\r\n"];
            NSArray<NSString *> *first = [lines.firstObject componentsSeparatedByString:@" "];
            if (first.count < 2) { close(fd); return; }
            NSMutableDictionary *headers = [NSMutableDictionary dictionary];
            for (NSString *line in [lines subarrayWithRange:NSMakeRange(1, lines.count - 1)]) {
                NSRange colon = [line rangeOfString:@":"];
                if (colon.location == NSNotFound) continue;
                headers[[line substringToIndex:colon.location].lowercaseString] =
                    [[line substringFromIndex:colon.location + 1] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
            }
            NSUInteger length = (NSUInteger)[headers[@"content-length"] integerValue];
            NSUInteger bodyStart = end.location + 4;
            while (buf.length < bodyStart + length) {
                ssize_t n = read(fd, chunk, sizeof chunk);
                if (n <= 0) { close(fd); return; }
                [buf appendBytes:chunk length:(NSUInteger)n];
            }
            TFRequest *req = [TFRequest new];
            req.method = first[0];
            req.target = first[1];
            NSRange qm = [req.target rangeOfString:@"?"];
            req.path = qm.location == NSNotFound ? req.target : [req.target substringToIndex:qm.location];
            req.query = qm.location == NSNotFound ? @{} : parseQuery([req.target substringFromIndex:qm.location + 1]);
            req.headers = headers;
            req.body = [buf subdataWithRange:NSMakeRange(bodyStart, length)];
            [buf replaceBytesInRange:NSMakeRange(0, bodyStart + length) withBytes:NULL length:0];

            TFResponse *resp = nil;
            @try {
                resp = [_router dispatch:req];
            } @catch (NSException *e) {
                _log([NSString stringWithFormat:@"   ERROR %@: %@", e.name, e.reason]);
                resp = [TFResponse json:@{@"errorCode": @500, @"message": @"local server error"} status:500];
            }
            NSString *tag = resp ? (resp.tag ? [@" " stringByAppendingString:resp.tag] : @"") : @" UNHANDLED";
            if (!resp) resp = [TFResponse json:@{@"errorCode": @404, @"message": @"not implemented by local server",
                                                 @"httpCode": @404} status:404];
            NSString *bodyNote = @"";
            if (req.body.length) {
                BOOL json = ((const char *)req.body.bytes)[0] == '{';
                BOOL payload = [req.method isEqualToString:@"PUT"] && [req.path containsString:@"payload"];
                NSUInteger shown = MIN(req.body.length, json ? 2000 : 300);
                bodyNote = payload ? [NSString stringWithFormat:@" body=<%lu bytes>", (unsigned long)req.body.length]
                                   : [NSString stringWithFormat:@" body=%@",
                                      [[NSString alloc] initWithData:[req.body subdataWithRange:NSMakeRange(0, shown)]
                                                            encoding:NSISOLatin1StringEncoding]];
            }
            _log([NSString stringWithFormat:@"%@ %@ -> %ld%@%@", req.method, req.target, (long)resp.status, tag, bodyNote]);

            NSData *body = [resp bodyBytes];
            NSMutableString *out = [NSMutableString stringWithFormat:@"HTTP/1.1 %ld %@\r\nContent-Type: %@\r\nContent-Length: %lu\r\n",
                                    (long)resp.status, resp.status == 200 ? @"OK" : @"Error", [resp contentType],
                                    (unsigned long)body.length];
            [resp.headers enumerateKeysAndObjectsUsingBlock:^(NSString *k, NSString *v, BOOL *stop) {
                [out appendFormat:@"%@: %@\r\n", k, v];
            }];
            [out appendString:@"\r\n"];
            NSMutableData *wire = [[out dataUsingEncoding:NSISOLatin1StringEncoding] mutableCopy];
            [wire appendData:body];
            BOOL closeAfter = [[headers[@"connection"] lowercaseString] isEqualToString:@"close"];
            if (!writeAll(fd, wire) || closeAfter) { close(fd); return; }
        }
    }
}
@end
