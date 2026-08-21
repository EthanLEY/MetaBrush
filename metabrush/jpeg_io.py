"""JPEG 文件 EXIF 写入：替换或插入 APP1(Exif) 段，保留其它所有段与图像数据。

解析原则：一旦发现结构异常（截断、非法长度、非法标记、未完整解析到 SOS/EOI），
立即抛出 ValueError —— 宁可跳过该文件，也绝不写出被截断/损坏的 JPEG。
"""

import struct
from typing import Iterator, Optional, Tuple

_SOI = b"\xff\xd8"
_EXIF_MAGIC = b"Exif\x00\x00"


def _validate_marker(marker: int) -> None:
    """JPEG 合法标记：0x01(TEM) 或 0xC0-0xFE（SOF/DHT/DQT/SOS/EOI/APPn/COM 等）。"""
    if marker != 0x01 and not (0xC0 <= marker <= 0xFE):
        raise ValueError(f"JPEG 标记非法（0x{marker:02X}），文件结构异常")


def _iter_segments(data: bytes) -> Iterator[Tuple[int, Optional[bytes], int]]:
    """逐个产出 JPEG 段 (marker, segment_bytes_or_None, next_pos)。

    遇到 SOS（扫描数据开始）或 EOI 后停止解析；扫描数据原样保留。
    segment_bytes 包含 2 字节长度字段（若有）。结构异常时抛出 ValueError。
    """
    n = len(data)
    pos = 2  # 跳过 SOI
    while pos < n:
        # 跳过填充的 0xFF
        while pos < n and data[pos] == 0xFF:
            pos += 1
        if pos >= n:
            raise ValueError("JPEG 解析失败：段标记缺失（文件在段之间被截断）")
        marker = data[pos]
        pos += 1
        _validate_marker(marker)
        if marker == 0xD9:      # EOI
            yield marker, None, pos
            return
        if marker == 0xDA:      # SOS
            if pos + 2 > n:
                raise ValueError("JPEG 解析失败：SOS 段长度字段被截断")
            length = struct.unpack(">H", data[pos:pos + 2])[0]
            seg = data[pos:pos + length]
            pos += length
            yield marker, seg, pos
            return
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:   # RSTn / TEM：无长度字段
            yield marker, None, pos
            continue
        if pos + 2 > n:
            raise ValueError("JPEG 解析失败：段长度字段被截断")
        length = struct.unpack(">H", data[pos:pos + 2])[0]
        if length < 2:
            raise ValueError(f"JPEG 解析失败：段长度非法（{length}）")
        if pos + length > n:
            raise ValueError(f"JPEG 解析失败：段长度越界（{length}，剩余 {n - pos} 字节）")
        # 段长度字段包含自身 2 字节：marker 之后共 length 字节
        seg = data[pos:pos + length]
        pos += length
        yield marker, seg, pos

    # 循环自然结束（无 SOS 也无 EOI）—— 文件结构不完整
    raise ValueError("JPEG 解析失败：未找到 SOS/EOI，文件结构不完整")


def insert_exif(data: bytes, exif_bytes: bytes) -> bytes:
    """在 JPEG 字节流中写入 EXIF APP1 段。

    参数:
        data:       原始 JPEG 字节
        exif_bytes: 序列化后的 EXIF，需以 b'Exif\\0\\0' 开头（piexif.dump 的输出）

    已有 EXIF 段会被替换，无 EXIF 则在 SOS 前插入；其它段（APP0/XMP/缩略图等）
    全部原样保留。结构异常时抛出 ValueError，绝不写出部分/截断的文件。
    """
    if not data.startswith(_SOI):
        raise ValueError("不是有效的 JPEG 文件（缺少 SOI 标记）")
    if not exif_bytes.startswith(_EXIF_MAGIC):
        raise ValueError("EXIF 数据缺少 Exif 头")

    app1 = b"\xff\xe1" + struct.pack(">H", len(exif_bytes) + 2) + exif_bytes
    out = bytearray(data[:2])
    inserted = False

    for marker, seg, next_pos in _iter_segments(data):
        if not inserted and marker == 0xE1 and seg is not None and seg[2:8] == _EXIF_MAGIC:
            # 替换已有 EXIF 段
            out += app1
            inserted = True
        elif marker == 0xDA:
            if not inserted:
                out += app1
                inserted = True
            out += b"\xff\xda" + seg
            out += data[next_pos:]       # 扫描数据 + 尾部原样保留
            return bytes(out)
        elif marker == 0xD9:
            if not inserted:
                out += app1
                inserted = True
            out += b"\xff\xd9"
            out += data[next_pos:]       # EOI 之后的尾部字节
            return bytes(out)
        else:
            # 元数据清洗：删除 AI 信息载体 —— XMP(APP1) 与 COM 注释段
            # （prompt/workflow/AICG 等文本常写在这里）
            if marker == 0xFE:
                continue
            if marker == 0xE1 and seg is not None and (
                    seg[2:].startswith(b"http://ns.adobe.com/xap/1.0/\x00")
                    or seg[2:].startswith(b"http://ns.adobe.com/xmp/extension/\x00")):
                continue
            if seg is None:
                out += bytes((0xFF, marker))
            else:
                out += bytes((0xFF, marker)) + seg

    # 到达此处说明未命中 SOS/EOI —— 解析不完整，禁止写出
    raise ValueError("JPEG 解析失败：未完整解析到图像数据，已跳过该文件")
