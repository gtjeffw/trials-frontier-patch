// Minimal HTTP/1.1 server for loopback use by the game (NSURLConnection) and a route table that service modules
// register with. One thread per connection, keep-alive, Content-Length bodies only (what the game sends).
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface TFRequest : NSObject
@property(nonatomic, copy) NSString *method;
@property(nonatomic, copy) NSString *target;  // path + query as sent
@property(nonatomic, copy) NSString *path;    // without query
@property(nonatomic, copy) NSDictionary<NSString *, NSArray<NSString *> *> *query;  // like urllib.parse.parse_qs
@property(nonatomic, copy) NSDictionary<NSString *, NSString *> *headers;           // lower-cased names
@property(nonatomic, copy) NSData *body;
/// First value of a query parameter, or nil.
- (nullable NSString *)param:(NSString *)name;
/// All values of a query parameter joined with "," then split on "," (like ",".join(query[name]).split(",")).
- (NSArray<NSString *> *)listParam:(NSString *)name;
@end

@interface TFResponse : NSObject
@property(nonatomic) NSInteger status;
@property(nonatomic, copy) NSDictionary<NSString *, NSString *> *headers;
@property(nonatomic, copy, nullable) NSData *data;  // raw body, or
@property(nonatomic, strong, nullable) id json;     // JSON object (serialised compact, slashes unescaped)
@property(nonatomic, copy, nullable) NSString *tag;  // log tag ("not offered")
+ (instancetype)json:(id)object status:(NSInteger)status;
+ (instancetype)json:(id)object;
+ (instancetype)data:(NSData *)data;
- (NSData *)bodyBytes;
- (NSString *)contentType;
@end

/// Returns a response, or nil to let later routes (and finally the UNHANDLED 404) try.
typedef TFResponse *_Nullable (^TFHandler)(TFRequest *request, NSArray<NSString *> *captures);

@interface TFRouter : NSObject
/// method nil = any; pattern is a regular expression that must match the whole path (captures passed to handler).
- (void)route:(nullable NSString *)method path:(NSString *)pattern handler:(TFHandler)handler;
- (nullable TFResponse *)dispatch:(TFRequest *)request;
@end

@interface TFHTTPServer : NSObject
- (instancetype)initWithPort:(uint16_t)port router:(TFRouter *)router log:(void (^)(NSString *line))log;
/// Binds 127.0.0.1:port and serves on background threads; NO if the port is taken.
- (BOOL)start:(NSError **)error;
@end

NS_ASSUME_NONNULL_END
