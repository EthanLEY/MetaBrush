"""根据预设生成完整的 EXIF 字典并序列化为可写入的字节。

拍摄时间（DateTimeOriginal / DateTimeDigitized）取处理时刻的系统时间；
GPS 经纬度由调用方传入（中国范围 纬度 18-54N、经度 73-135E），每张图独立随机。
"""

import math
from datetime import datetime, timezone
from typing import Optional, Tuple

import piexif
from piexif import ExifIFD, GPSIFD, ImageIFD

from .presets import Preset

# 中国范围
GPS_LAT_MIN, GPS_LAT_MAX = 18.0, 54.0
GPS_LON_MIN, GPS_LON_MAX = 73.0, 135.0


def gps_bounds() -> Tuple[float, float, float, float]:
    """返回 (纬度下限, 纬度上限, 经度下限, 经度上限)。"""
    return GPS_LAT_MIN, GPS_LAT_MAX, GPS_LON_MIN, GPS_LON_MAX


def _dms(value: float):
    """将十进制度数转换为 EXIF 的 度/分/秒 有理数列表。"""
    value = max(0.0, min(value, 359.999999))
    d = int(value)
    m_float = (value - d) * 60.0
    m = int(m_float)
    s = round((m_float - m) * 60.0, 2)
    if s >= 60.0:
        s -= 60.0
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return [(d, 1), (m, 1), (int(round(s * 100)), 100)]


def _apex_aperture(f_number: Tuple[int, int]) -> Tuple[int, int]:
    """由 F 值换算 APEX 光圈值：Av = 2*log2(f)。"""
    f = f_number[0] / f_number[1]
    av = round(2.0 * math.log2(f), 2)
    return (int(round(av * 100)), 100)


def _apex_shutter(exposure: Tuple[int, int]) -> Tuple[int, int]:
    """由曝光时间换算 APEX 快门速度值：Tv = -log2(t)。"""
    t = exposure[0] / exposure[1]
    tv = round(-math.log2(t), 2)
    return (int(round(tv * 100)), 100)


def build_exif_dict(preset: Preset, now: datetime, lat: float, lon: float,
                    image_size: Optional[Tuple[int, int]] = None,
                    alt: int = 0) -> dict:
    """构建完整 EXIF 字典。

    参数:
        preset:      预设模板
        now:         处理时刻（系统时间），写入 EXIF 时间字段
        lat / lon:   随机 GPS 经纬度（十进制度）
        image_size:  图像宽高 (w, h)，可选
        alt:         随机海拔（米，整数）
    """
    dt_str = now.strftime("%Y:%m:%d %H:%M:%S")
    utc = datetime.now(timezone.utc)

    exif_dict = {
        "0th": {
            ImageIFD.Make: preset["make"],
            ImageIFD.Model: preset["model"],
            ImageIFD.Orientation: 1,
            ImageIFD.DateTime: dt_str,
            ImageIFD.XResolution: (72, 1),
            ImageIFD.YResolution: (72, 1),
            ImageIFD.ResolutionUnit: 2,   # 英寸
        },
        "Exif": {
            ExifIFD.ExposureTime: preset["shutter"],
            ExifIFD.FNumber: preset["f_number"],
            ExifIFD.ExposureProgram: preset["exposure_program"],
            ExifIFD.ISOSpeedRatings: preset["iso"],
            ExifIFD.DateTimeOriginal: dt_str,
            ExifIFD.DateTimeDigitized: dt_str,
            ExifIFD.ShutterSpeedValue: _apex_shutter(preset["shutter"]),
            ExifIFD.ApertureValue: _apex_aperture(preset["f_number"]),
            ExifIFD.FocalLength: preset["focal_length"],
            ExifIFD.MeteringMode: preset["metering_mode"],
            ExifIFD.WhiteBalance: 0,      # 自动
            ExifIFD.ColorSpace: 1,        # sRGB
            ExifIFD.ExifVersion: b"0231",
            ExifIFD.FlashpixVersion: b"0100",
            ExifIFD.ComponentsConfiguration: b"\x01\x02\x03\x00",
            ExifIFD.LensMake: preset["lens_make"],
            ExifIFD.LensModel: preset["lens_model"],
        },
        "GPS": {
            GPSIFD.GPSVersionID: (2, 3, 0, 0),
            GPSIFD.GPSLatitudeRef: "N",
            GPSIFD.GPSLatitude: _dms(lat),
            GPSIFD.GPSLongitudeRef: "E",
            GPSIFD.GPSLongitude: _dms(lon),
            GPSIFD.GPSAltitudeRef: 0,     # 海平面以上
            GPSIFD.GPSAltitude: (max(0, int(alt)), 1),
            GPSIFD.GPSTimeStamp: [(utc.hour, 1), (utc.minute, 1), (utc.second, 1)],
            GPSIFD.GPSDateStamp: utc.strftime("%Y:%m:%d"),
        },
        "1st": {},
        "thumbnail": None,
    }

    if image_size:
        exif_dict["Exif"][ExifIFD.PixelXDimension] = int(image_size[0])
        exif_dict["Exif"][ExifIFD.PixelYDimension] = int(image_size[1])

    return exif_dict


def dump_exif(exif_dict: dict) -> bytes:
    """将 EXIF 字典序列化为字节（含 JPEG 所需的 b'Exif\\0\\0' 头）。"""
    return piexif.dump(exif_dict)
