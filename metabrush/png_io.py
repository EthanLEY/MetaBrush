"""PNG 文件 EXIF 写入与元数据清洗。

需求（新）：
  原图元数据仅保留基础图像信息（IHDR 的宽高/位深/色彩类型/压缩/滤波/隔行），
  删除 prompt / workflow / AICG 等所有附属元数据（tEXt、zTXt、iTXt、eXIf、
  tIME、gAMA、pHYs 等一律不保留）；只额外保留渲染必需的块（PLTE 调色板、
  tRNS 透明、以及未知的关键块），并丢弃 IEND 之后的尾部字节。
  然后插入我们的 eXIf 块（严格位于 IHDR 之后，符合 PNG 规范）。

依据 PNG 规范：eXIf 块数据为不含 JPEG APP1 "Exif\\0\\0" 头与长度字段的
原始 EXIF（TIFF）数据；IHDR 必须是第一个块。
"""

import struct
import zlib

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(c_type: bytes, c_data: bytes) -> bytes:
    crc = zlib.crc32(c_type + c_data) & 0xFFFFFFFF
    return struct.pack(">I", len(c_data)) + c_type + c_data + struct.pack(">I", crc)


def _is_critical(c_type: bytes) -> bool:
    """PNG 关键块：类型名首字母大写（bit5=0）。"""
    return (c_type[0] & 0x20) == 0


def insert_exif(data: bytes, exif_tiff_bytes: bytes) -> bytes:
    """清洗并写入 eXIf。

    参数:
        data:            原始 PNG 字节
        exif_tiff_bytes: 不含 'Exif\\0\\0' 头的原始 EXIF（TIFF）数据

    返回：仅含 IHDR + eXIf + (PLTE/tRNS/未知关键块) + IDAT + IEND 的完整 PNG。
    结构异常时抛出 ValueError，绝不写出半截/损坏的文件。
    """
    if not data.startswith(_SIG):
        raise ValueError("不是有效的 PNG 文件（签名不匹配）")

    out = bytearray(_SIG)
    inserted = False
    pos = 8
    n = len(data)

    while pos + 12 <= n:
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        c_type = data[pos + 4:pos + 8]
        c_start, c_end = pos, pos + 12 + length
        if c_end > n:
            raise ValueError("PNG 块长度越界（文件损坏）")

        if c_type == b"IHDR":
            # PNG 规范：IHDR 必须是第一个块 —— 先写 IHDR，eXIf 紧随其后
            out += data[c_start:c_end]
            if not inserted:
                out += _chunk(b"eXIf", exif_tiff_bytes)
                inserted = True
        elif c_type == b"IEND":
            out += data[c_start:c_end]
            # 丢弃 IEND 之后的尾部字节（可能是残留元数据）
            return bytes(out)
        elif c_type == b"tRNS" or _is_critical(c_type):
            # 保留：透明块（tRNS）与关键块（PLTE/IDAT/未知关键块如 CgBI）。
            # 其余所有附属元数据块（tEXt/zTXt/iTXt/eXIf/tIME/gAMA/pHYs 等）
            # 一律删除。
            out += data[c_start:c_end]

        pos = c_end

    # 未遇到 IEND：文件被截断/不完整，禁止写出
    raise ValueError("PNG 解析失败：未找到 IEND 块，文件结构不完整")
