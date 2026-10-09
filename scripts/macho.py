"""Minimal helpers for the thin arm64 TrialsFrontier Mach-O."""
import hashlib
import struct

LC_ENCRYPTION_INFO_64 = 0x2C


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def encryption_info(data):
    """Return (load_command_offset, cryptoff, cryptsize, cryptid) for LC_ENCRYPTION_INFO_64."""
    magic, _, _, _, ncmds = struct.unpack_from("<5I", data, 0)
    if magic != 0xFEEDFACF:
        raise ValueError("expected a thin 64-bit Mach-O")
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<2I", data, off)
        if cmd == LC_ENCRYPTION_INFO_64:
            cryptoff, cryptsize, cryptid = struct.unpack_from("<3I", data, off + 8)
            return off, cryptoff, cryptsize, cryptid
        off += size
    raise ValueError("no LC_ENCRYPTION_INFO_64")


def text_section_offset(data):
    """File offset of the __TEXT,__text section (code caves must end before it)."""
    _, _, _, _, ncmds = struct.unpack_from("<5I", data, 0)
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<2I", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            nsects = struct.unpack_from("<I", data, off + 64)[0]
            for i in range(nsects):
                s = off + 72 + 80 * i
                if data[s:s + 16].rstrip(b"\0") == b"__text" and data[s + 16:s + 32].rstrip(b"\0") == b"__TEXT":
                    return struct.unpack_from("<I", data, s + 48)[0]
        off += size
    raise ValueError("no __TEXT,__text section")

def apply_decrypted_page(data, page):
    """Return a copy of `data` with the encrypted range replaced by `page` and cryptid set to 0."""
    out = bytearray(data)
    lc, cryptoff, cryptsize, _ = encryption_info(out)
    if len(page) != cryptsize:
        raise ValueError(f"page is {len(page)} bytes, expected {cryptsize}")
    out[cryptoff:cryptoff + cryptsize] = page
    struct.pack_into("<I", out, lc + 16, 0)
    return bytes(out)
