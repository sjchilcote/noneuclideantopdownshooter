"""JUCE binary ValueTree -> XML converter.

Format transcribed from JUCE 7.0.12 sources (fetched, not recalled):
juce_ValueTree.cpp SharedObject::writeToStream / readFromStream and
juce_Variant.cpp var::readFromStream:

    tree      := string(type) compressedInt(nProps)
                 { string(name) var }*  compressedInt(nChildren) tree*
    string    := UTF-8 bytes, NUL terminated
    compInt   := 1 byte n (|0x80 if negative), then n little-endian bytes
    var       := compressedInt(len) marker payload[len-1]
    markers   := 1 int32le | 2 true | 3 false | 4 double64le | 5 utf8+NUL
                 | 6 int64le | 7 array (compInt count, then vars)
                 | 8 binary (raw bytes)

XML emission follows ValueTree::createXml conventions: properties become
attributes; MemoryBlock properties become `base64:<name>` attributes in
JUCE MemoryBlock::toBase64Encoding.
"""
from __future__ import annotations

import struct
from xml.sax.saxutils import quoteattr

_TABLE = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _mb_b64(data: bytes) -> str:
    nbits = len(data) * 8
    out = []
    for i in range((nbits + 5) // 6):
        v = 0
        for b in range(6):
            k = i * 6 + b
            if k < nbits and (data[k >> 3] >> (k & 7)) & 1:
                v |= 1 << b
        out.append(_TABLE[v])
    return str(len(data)) + "." + "".join(out)


class _R:
    def __init__(self, buf: bytes):
        self.b = buf
        self.i = 0

    def string(self) -> str:
        j = self.b.index(0, self.i)
        s = self.b[self.i:j].decode("utf-8")
        self.i = j + 1
        return s

    def cint(self) -> int:
        n = self.b[self.i]
        self.i += 1
        neg = bool(n & 0x80)
        n &= 0x7F
        v = int.from_bytes(self.b[self.i:self.i + n], "little")
        self.i += n
        return -v if neg else v

    def take(self, n: int) -> bytes:
        v = self.b[self.i:self.i + n]
        self.i += n
        return v


def _read_var(r: _R):
    n = r.cint()
    if n <= 0:
        return None
    m = r.take(1)[0]
    if m == 1:
        return struct.unpack("<i", r.take(4))[0]
    if m == 2:
        return True
    if m == 3:
        return False
    if m == 4:
        return struct.unpack("<d", r.take(8))[0]
    if m == 5:
        return r.take(n - 1).split(b"\0")[0].decode("utf-8")
    if m == 6:
        return struct.unpack("<q", r.take(8))[0]
    if m == 7:
        return [_read_var(r) for _ in range(r.cint())]
    if m == 8:
        return r.take(n - 1)  # MemoryBlock
    raise ValueError(f"unknown var marker {m} at {r.i}")


def read_tree(r: _R):
    typ = r.string()
    if not typ:
        return None
    props = []
    for _ in range(r.cint()):
        name = r.string()
        props.append((name, _read_var(r)))
    children = [read_tree(r) for _ in range(r.cint())]
    return (typ, props, [c for c in children if c is not None])


def parse(buf: bytes):
    return read_tree(_R(buf))


def _attr(name: str, val) -> str:
    if isinstance(val, bytes):
        return f"base64:{name}={quoteattr(_mb_b64(val))}"
    if isinstance(val, bool):
        return f"{name}={quoteattr('1' if val else '0')}"
    if isinstance(val, float):
        return f"{name}={quoteattr(repr(val))}"
    return f"{name}={quoteattr(str(val))}"


def to_xml(tree) -> str:
    typ, props, children = tree
    head = " ".join([typ] + [_attr(k, v) for k, v in props])
    if not children:
        return f"<{head}/>"
    body = "".join(to_xml(c) for c in children)
    return f"<{head}>{body}</{typ}>"


def binary_to_xml(buf: bytes) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?> '
            + to_xml(parse(buf)))
