// Generated rider avatars (pixel-art helmets) for riders without a picture; byte-identical port of
// server/avatars.py (see there for the design). tests/test_parity.py compares the two.
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// 146x146 PNG for a rider id (or any string), e.g. a profile id or "fallback".
NSData *TFAvatarPNG(NSString *seed);

NS_ASSUME_NONNULL_END
