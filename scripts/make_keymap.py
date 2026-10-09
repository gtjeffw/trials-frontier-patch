"""Write a PlayCover keymap for Trials Frontier (keyboard -> on-screen touch buttons).

Usage: python3 -I make_keymap.py <out.plist> [--buttons]

Default layout: one PlayCover keyboard *joystick* per thumb. On the iPad each thumb is a single finger sliding between
two buttons (lean back/forward on the left, brake/throttle on the right). The game assigns a finger to a button only
when it goes down and tracks two fingers, so one virtual finger per key (--buttons, the old layout) loses a third
key held during a quick change and never picks it up again. A PlayTools joystick is one finger: a key moves it to
centre +/- shift (shift = size * screen width / 400), the most recent key wins, releasing it slides the finger back
to the other held key, and the finger lifts when no key is held. Arrows and WASD each get their own pair of joysticks
(use one scheme at a time); the joystick's unused up/down keys are bound to F5-F12.
Install: copy to ~/Library/Containers/io.playcover.PlayCover/Keymapping/com.ubisoft.redlynx.trialsfrontier.plist
(with the game closed), then enable Keymapping for the app in PlayCover's settings.

Positions are fractions of the game screen (PlayTools: absoluteX = xCoord * screen.width), measured from the
in-race HUD; size is in PlayTools' percent units. Key codes are HID usages as in PlayCover's KeyCodeNames.
"""
import plistlib
import sys

HID = {"Up": 82, "Down": 81, "Left": 80, "Right": 79, "W": 26, "S": 22, "A": 4, "D": 7, "Space": 44, "Esc": 41}
BUTTONS = [  # (action, (x, y), keys)
    ("throttle", (0.921, 0.884), ["Up", "W"]),
    ("brake", (0.779, 0.893), ["Down", "S"]),
    ("lean back", (0.079, 0.893), ["Left", "A"]),
    ("lean forward", (0.214, 0.903), ["Right", "D"]),
    ("restart (tap: checkpoint, hold: full reset)", (0.932, 0.065), ["Space"]),
    ("pause", (0.049, 0.060), ["Esc"]),
]

HID.update({"F5": 62, "F6": 63, "F7": 64, "F8": 65, "F9": 66, "F10": 67, "F11": 68, "F12": 69})
PAIRS = [  # (left button, right button, left key, right key, unused up/down keys)
    ("lean back", "lean forward", "Left", "Right", ("F5", "F6")),
    ("brake", "throttle", "Down", "Up", ("F7", "F8")),
    ("lean back", "lean forward", "A", "D", ("F9", "F10")),
    ("brake", "throttle", "S", "W", ("F11", "F12")),
]
pos = {name: xy for name, xy, _ in BUTTONS}

if "--buttons" in sys.argv:
    sys.argv.remove("--buttons")
    models = [{"keyCode": HID[k], "keyName": k, "transform": {"xCoord": x, "yCoord": y, "size": 6.0}}
              for _, (x, y), keys in BUTTONS for k in keys]
    joysticks = []
else:
    models = [{"keyCode": HID[k], "keyName": k, "transform": {"xCoord": x, "yCoord": y, "size": 6.0}}
              for name, (x, y), keys in BUTTONS if name.startswith(("restart", "pause")) for k in keys]
    joysticks = []
    for left, right, lkey, rkey, (up, down) in PAIRS:
        (x1, y1), (x2, y2) = pos[left], pos[right]
        joysticks.append({"upKeyCode": HID[up], "downKeyCode": HID[down], "leftKeyCode": HID[lkey],
                          "rightKeyCode": HID[rkey], "keyName": "Keyboard",
                          "transform": {"xCoord": round((x1 + x2) / 2, 4), "yCoord": round((y1 + y2) / 2, 4),
                                        "size": round((x2 - x1) / 2 * 400, 2)}})
keymap = {"buttonModels": models, "draggableButtonModels": [], "joystickModel": joysticks, "mouseAreaModel": [],
          "bundleIdentifier": "com.ubisoft.redlynx.trialsfrontier", "version": "2.0.0"}
with open(sys.argv[1], "wb") as f:
    plistlib.dump(keymap, f, fmt=plistlib.FMT_XML)
print(f"wrote {sys.argv[1]}: {len(models)} buttons, {len(joysticks)} joysticks")
