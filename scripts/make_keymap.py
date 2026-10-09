"""Write a PlayCover keymap for Trials Frontier (keyboard -> on-screen touch buttons).

Usage: python3 -I make_keymap.py <out.plist>
Install: copy to ~/Library/Containers/io.playcover.PlayCover/Keymapping/com.ubisoft.redlynx.trialsfrontier.plist
(with the game closed), then enable Keymapping for the app in PlayCover's settings.

Positions are fractions of the game screen (PlayTools: absoluteX = xCoord * screen.width), measured from the
in-race HUD; size is in PlayTools' percent units. Key codes are HID usages as in PlayCover's KeyCodeNames.
"""
import plistlib
import sys

HID = {"Up": 82, "Down": 81, "Left": 80, "Right": 79, "W": 26, "S": 22, "A": 4, "D": 7, "R": 21, "P": 19}
BUTTONS = [  # (action, (x, y), keys)
    ("throttle", (0.921, 0.884), ["Up", "W"]),
    ("brake", (0.779, 0.893), ["Down", "S"]),
    ("lean back", (0.079, 0.893), ["Left", "A"]),
    ("lean forward", (0.214, 0.903), ["Right", "D"]),
    ("restart", (0.932, 0.065), ["R"]),
    ("pause", (0.049, 0.060), ["P"]),
]

models = [{"keyCode": HID[k], "keyName": k, "transform": {"xCoord": x, "yCoord": y, "size": 6.0}}
          for _, (x, y), keys in BUTTONS for k in keys]
keymap = {"buttonModels": models, "draggableButtonModels": [], "joystickModel": [], "mouseAreaModel": [],
          "bundleIdentifier": "com.ubisoft.redlynx.trialsfrontier", "version": "2.0.0"}
with open(sys.argv[1], "wb") as f:
    plistlib.dump(keymap, f, fmt=plistlib.FMT_XML)
print(f"wrote {sys.argv[1]}: {len(models)} key bindings")
