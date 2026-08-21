"""MetaBrush 核心逻辑无界面测试。

运行方式（在项目根目录）：
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
或：
    .venv\\Scripts\\python.exe tests\\test_core.py
"""

import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import piexif
from PIL import Image

from metabrush import jpeg_io, png_io
from metabrush.exif_builder import gps_bounds
from metabrush.presets import DEFAULT_PRESET, PRESETS
from metabrush.processor import process_file


def _ascii(value):
    if isinstance(value, bytes):
        return value.decode("ascii", "replace")
    return str(value)


def _from_dms(dms):
    d = dms[0][0] / dms[0][1]
    m = dms[1][0] / dms[1][1]
    s = dms[2][0] / dms[2][1]
    return d + m / 60.0 + s / 3600.0


class MetaBrushCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="metabrush_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- 工具 ----------
    def _make_jpeg(self, name="a.jpg", with_exif=False, size=(640, 480)):
        path = os.path.join(self.tmp, name)
        Image.new("RGB", size, (140, 90, 210)).save(path, "JPEG", quality=92)
        if with_exif:
            old = {
                "0th": {piexif.ImageIFD.Make: "FUJIFILM", piexif.ImageIFD.Model: "X-T4"},
                "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None,
            }
            piexif.insert(piexif.dump(old), path)
        return path

    def _make_png(self, name="b.png", size=(320, 240)):
        path = os.path.join(self.tmp, name)
        Image.new("RGBA", size, (30, 160, 90, 255)).save(path, "PNG")
        return path

    def _snapshot(self, path):
        st = os.stat(path)
        return (st.st_mtime, st.st_ctime, st.st_size)

    # ---------- JPEG ----------
    def test_jpeg_fields_time_and_timestamps(self):
        path = self._make_jpeg()
        before = self._snapshot(path)
        now = datetime(2024, 5, 6, 7, 8, 9)
        ok, err = process_file(path, DEFAULT_PRESET, now=now)
        self.assertTrue(ok, err)
        exif = piexif.load(path)
        self.assertEqual(_ascii(exif["0th"][piexif.ImageIFD.Make]), "Canon")
        self.assertEqual(_ascii(exif["0th"][piexif.ImageIFD.Model]), "Canon EOS R5")
        self.assertEqual(_ascii(exif["0th"][piexif.ImageIFD.DateTime]), "2024:05:06 07:08:09")
        self.assertEqual(_ascii(exif["Exif"][piexif.ExifIFD.DateTimeOriginal]),
                         "2024:05:06 07:08:09")
        self.assertEqual(_ascii(exif["Exif"][piexif.ExifIFD.DateTimeDigitized]),
                         "2024:05:06 07:08:09")
        self.assertEqual(exif["Exif"][piexif.ExifIFD.FNumber], (4, 1))
        self.assertEqual(exif["Exif"][piexif.ExifIFD.ExposureTime], (1, 125))
        self.assertEqual(exif["Exif"][piexif.ExifIFD.ISOSpeedRatings], 100)
        self.assertEqual(exif["Exif"][piexif.ExifIFD.FocalLength], (24, 1))
        self.assertEqual(_ascii(exif["Exif"][piexif.ExifIFD.LensModel]),
                         "RF24-105mm F4 L IS USM")
        # 修改时间 / 创建时间绝对不变
        after = self._snapshot(path)
        self.assertAlmostEqual(after[0], before[0], delta=0.01)
        if os.name == "nt":
            self.assertEqual(after[1], before[1])   # Windows st_ctime = 创建时间

    def test_jpeg_gps_in_china_range(self):
        path = self._make_jpeg()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        gps = piexif.load(path)["GPS"]
        self.assertEqual(_ascii(gps[piexif.GPSIFD.GPSLatitudeRef]), "N")
        self.assertEqual(_ascii(gps[piexif.GPSIFD.GPSLongitudeRef]), "E")
        lat = _from_dms(gps[piexif.GPSIFD.GPSLatitude])
        lon = _from_dms(gps[piexif.GPSIFD.GPSLongitude])
        lo_lat, hi_lat, lo_lon, hi_lon = gps_bounds()
        self.assertTrue(lo_lat <= lat <= hi_lat, f"纬度越界: {lat}")
        self.assertTrue(lo_lon <= lon <= hi_lon, f"经度越界: {lon}")

    def test_gps_independent_per_image(self):
        p1 = self._make_jpeg("1.jpg")
        p2 = self._make_jpeg("2.jpg")
        process_file(p1, DEFAULT_PRESET)
        process_file(p2, DEFAULT_PRESET)
        g1 = piexif.load(p1)["GPS"]
        g2 = piexif.load(p2)["GPS"]
        lat1, lon1 = _from_dms(g1[piexif.GPSIFD.GPSLatitude]), _from_dms(g1[piexif.GPSIFD.GPSLongitude])
        lat2, lon2 = _from_dms(g2[piexif.GPSIFD.GPSLatitude]), _from_dms(g2[piexif.GPSIFD.GPSLongitude])
        self.assertNotEqual((lat1, lon1), (lat2, lon2))

    def test_jpeg_existing_exif_replaced(self):
        path = self._make_jpeg(with_exif=True)
        ok, err = process_file(path, "索尼A7M4")
        self.assertTrue(ok, err)
        exif = piexif.load(path)
        self.assertEqual(_ascii(exif["0th"][piexif.ImageIFD.Make]), "SONY")
        self.assertEqual(_ascii(exif["0th"][piexif.ImageIFD.Model]), "ILCE-7M4")

    def test_jpeg_still_decodable(self):
        path = self._make_jpeg()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        with Image.open(path) as im:
            im.load()
            self.assertEqual(im.size, (640, 480))

    # ---------- PNG ----------
    def test_png_exif_readable_by_pillow(self):
        path = self._make_png()
        before = self._snapshot(path)
        ok, err = process_file(path, "尼康Z8")
        self.assertTrue(ok, err)
        with Image.open(path) as im:
            exif = im.getexif()
        self.assertEqual(exif.get(piexif.ImageIFD.Make), "NIKON CORPORATION")
        self.assertEqual(exif.get(piexif.ImageIFD.Model), "NIKON Z 8")
        after = self._snapshot(path)
        self.assertAlmostEqual(after[0], before[0], delta=0.01)
        if os.name == "nt":
            self.assertEqual(after[1], before[1])

    def test_png_gps_present(self):
        path = self._make_png()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        with Image.open(path) as im:
            exif = im.getexif()
        gps = exif.get_ifd(0x8825)   # GPS IFD
        self.assertIn(2, gps)        # GPSLatitude
        self.assertIn(4, gps)        # GPSLongitude

    def test_png_still_decodable(self):
        path = self._make_png()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        with Image.open(path) as im:
            im.load()
            self.assertEqual(im.size, (320, 240))
            self.assertEqual(im.mode, "RGBA")

    def test_png_exif_without_header_roundtrip(self):
        # 直接验证 png_io：写入不含 Exif 头的 TIFF 数据后 PIL 可读
        path = self._make_png("round.png")
        with open(path, "rb") as f:
            data = f.read()
        exif_dict = {
            "0th": {piexif.ImageIFD.Make: "Canon"}, "Exif": {},
            "GPS": {}, "1st": {}, "thumbnail": None,
        }
        exif_bytes = piexif.dump(exif_dict)
        new_data = png_io.insert_exif(data, exif_bytes[6:])
        with open(path, "wb") as f:
            f.write(new_data)
        with Image.open(path) as im:
            self.assertEqual(im.getexif().get(piexif.ImageIFD.Make), "Canon")

    # ---------- 异常与边界 ----------
    def test_corrupt_jpeg_skipped(self):
        path = os.path.join(self.tmp, "bad.jpg")
        with open(path, "wb") as f:
            f.write(b"this is not a jpeg at all")
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_corrupt_png_skipped(self):
        path = os.path.join(self.tmp, "bad.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nnot really a png")
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_unsupported_extension(self):
        path = os.path.join(self.tmp, "notes.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("hello")
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIn("不支持", err)

    def test_jpeg_io_requires_exif_header(self):
        with self.assertRaises(ValueError):
            jpeg_io.insert_exif(b"\xff\xd8\xff\xd9", b"\x49\x49\x2a\x00")

    def test_jpeg_bad_length_skipped_unchanged(self):
        # 段长度字段越界：必须跳过且文件原样保留，绝不能截断写出
        path = self._make_jpeg()
        with open(path, "r+b") as f:
            f.seek(4)
            f.write(b"\xff\xff")       # APP0 长度改为 0xFFFF，远超文件末尾
        with open(path, "rb") as f:
            before = f.read()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIn("解析失败", err)
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(after, before)   # 文件未被修改

    def test_jpeg_invalid_marker_skipped_unchanged(self):
        # 非法标记字节：必须跳过且文件原样保留
        path = self._make_jpeg()
        with open(path, "r+b") as f:
            f.seek(2)
            f.write(b"\xff\x32")       # 把 APP0 标记改成非法 0x32
        with open(path, "rb") as f:
            before = f.read()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(after, before)

    def test_jpeg_missing_eoi_skipped_unchanged(self):
        # 无 EOI/SOS 的残缺结构：必须跳过且文件原样保留
        path = self._make_jpeg()
        with open(path, "rb") as f:
            data = f.read()
        # 截断为「SOI + 一个完整段」且无 SOS/EOI
        with open(path, "wb") as f:
            f.write(data[:20])         # SOI + APP0，之后戛然而止
        with open(path, "rb") as f:
            before = f.read()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(after, before)

    def test_png_missing_iend_skipped_unchanged(self):
        # PNG 无 IEND（被截断）：必须跳过且文件原样保留
        path = self._make_png()
        with open(path, "rb") as f:
            data = f.read()
        iend = data.rfind(b"IEND")
        with open(path, "wb") as f:
            f.write(data[:iend])       # 去掉 IEND
        with open(path, "rb") as f:
            before = f.read()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertFalse(ok)
        self.assertIn("解析失败", err)
        with open(path, "rb") as f:
            after = f.read()
        self.assertEqual(after, before)

    def test_atomic_write_no_leftover_temp(self):
        # 原子写入后：同目录不应残留临时文件
        path = self._make_jpeg()
        directory = os.path.dirname(path)
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        leftovers = [n for n in os.listdir(directory) if "metabrush_tmp" in n]
        self.assertEqual(leftovers, [])

    def test_png_ihdr_must_be_first_chunk(self):
        # 回归：eXIf 必须插在 IHDR 之后（PNG 规范要求 IHDR 是第一个块），
        # 否则严格校验工具会把图片判为损坏
        import struct as _struct
        path = self._make_png()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        with open(path, "rb") as f:
            data = f.read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        (length,) = _struct.unpack(">I", data[8:12])
        c_type = data[12:16]
        self.assertEqual(c_type, b"IHDR", "第一个块必须是 IHDR")
        # eXIf 应为第二个块
        (length2,) = _struct.unpack(">I", data[8 + 12 + length:8 + 12 + length + 4])
        c_type2 = data[8 + 12 + length + 4:8 + 12 + length + 8]
        self.assertEqual(c_type2, b"eXIf", "第二个块应为 eXIf")

    # ---------- 元数据清洗 ----------
    @staticmethod
    def _chunk(c_type, c_data):
        crc = zlib.crc32(c_type + c_data) & 0xFFFFFFFF
        return struct.pack(">I", len(c_data)) + c_type + c_data + struct.pack(">I", crc)

    def _png_chunk_types(self, path):
        with open(path, "rb") as f:
            d = f.read()
        types = []
        pos = 8
        while pos + 12 <= len(d):
            ln = struct.unpack(">I", d[pos:pos + 4])[0]
            types.append(d[pos + 4:pos + 8])
            if d[pos + 4:pos + 8] == b"IEND":
                break
            pos += 12 + ln
        return types

    def test_png_strips_ai_metadata(self):
        # 删除 prompt/workflow/AICG 等附属元数据：tEXt/zTXt/iTXt/eXIf/tIME/gAMA/pHYs
        path = self._make_png()
        with open(path, "rb") as f:
            data = f.read()
        after_ihdr = 8 + 12 + struct.unpack(">I", data[8:12])[0]
        anc = b"".join([
            self._chunk(b"tEXt", b"prompt\x00a workflow prompt json"),
            self._chunk(b"tEXt", b"workflow\x00{\"nodes\":[]}"),
            self._chunk(b"tEXt", b"parameters\x00steps:20, cfg:4"),
            self._chunk(b"tEXt", b"Description\x00AICG generated"),
            self._chunk(b"zTXt", b"prompt\x00\x00" + zlib.compress(b"hidden prompt")),
            self._chunk(b"iTXt", b"Comment\x00\x00\x00\x00\x00AI text"),
            self._chunk(b"gAMA", struct.pack(">I", 45455)),
            self._chunk(b"pHYs", struct.pack(">IIB", 3780, 3780, 1)),
            self._chunk(b"tIME", struct.pack(">HBBBBB", 2026, 8, 21, 10, 0, 0)),
            self._chunk(b"eXIf", b"\x49\x49\x2a\x00" + b"\x00" * 20),
        ])
        with open(path, "wb") as f:
            f.write(data[:after_ihdr] + anc + data[after_ihdr:])
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        types = self._png_chunk_types(path)
        # 只应保留：IHDR, eXIf, IDAT, IEND
        self.assertEqual(types, [b"IHDR", b"eXIf", b"IDAT", b"IEND"], f"残留块: {types}")
        # 整文件里不应出现 prompt/workflow/AICG 字样
        with open(path, "rb") as f:
            blob = f.read()
        for bad in (b"prompt", b"workflow", b"AICG", b"parameters"):
            self.assertNotIn(bad.lower(), blob.lower(), f"仍包含 {bad}")

    def test_png_keeps_palette_and_transparency(self):
        # 调色板 PNG：必须保留 PLTE（否则无法解码）；带 tRNS 的 RGB PNG 保留 tRNS
        p = os.path.join(self.tmp, "pal.png")
        im = Image.new("P", (64, 48))
        im.putpalette([i % 256 for i in range(768)])
        im.putpixel((0, 0), 3)
        im.putpixel((1, 1), 7)
        im.save(p, "PNG")
        ok, err = process_file(p, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        types = self._png_chunk_types(p)
        self.assertIn(b"PLTE", types)
        with Image.open(p) as im2:
            im2.load()
            self.assertEqual(im2.mode, "P")

    def test_jpeg_strips_xmp_and_com(self):
        # JPEG 删除 XMP(APP1) 与 COM 段（AI 元数据载体）
        path = self._make_jpeg()
        with open(path, "rb") as f:
            orig = f.read()
        xmp = b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>prompt</x:xmpmeta>"
        com = b"prompt: hello workflow"
        segs = (b"\xff\xe1" + struct.pack(">H", len(xmp) + 2) + xmp +
                b"\xff\xfe" + struct.pack(">H", len(com) + 2) + com)
        with open(path, "wb") as f:
            f.write(b"\xff\xd8" + segs + orig[2:])   # SOI 之后插入 XMP+COM，保留其余段
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        with open(path, "rb") as f:
            blob = f.read()
        self.assertNotIn(b"xap/1.0", blob)
        self.assertNotIn(b"\xff\xfe", blob)   # COM 段已删除
        self.assertNotIn(b"prompt", blob.lower())
        with Image.open(path) as im:
            im.load()
            self.assertEqual(im.size, (640, 480))

    def test_exif_has_no_software(self):
        # 新写入的 EXIF 不允许出现 Software=MetaBrush
        path = self._make_jpeg()
        ok, err = process_file(path, DEFAULT_PRESET)
        self.assertTrue(ok, err)
        exif = piexif.load(path)
        self.assertNotIn(piexif.ImageIFD.Software, exif["0th"])

    def test_presets_are_distinct(self):
        models = {PRESETS[k]["model"] for k in PRESETS}
        self.assertEqual(len(models), len(PRESETS))
        self.assertEqual(len(PRESETS), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
