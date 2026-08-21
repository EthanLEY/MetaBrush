"""预设模板：不同相机机身的 EXIF 字段模板。

字段约定：
    make / model            厂商与机身型号
    lens_make / lens_model  镜头厂商与镜头型号
    f_number                光圈 F 值（有理数 (n, d)）
    shutter                 快门时间（有理数，秒）
    iso                     感光度（整数）
    focal_length            焦距（有理数，mm）
    exposure_program        曝光程序（EXIF 枚举值）
    metering_mode           测光模式（EXIF 枚举值）
"""

from typing import Any, Dict

Preset = Dict[str, Any]

PRESETS: Dict[str, Preset] = {
    "佳能R5": {
        "make": "Canon",
        "model": "Canon EOS R5",
        "lens_make": "Canon",
        "lens_model": "RF24-105mm F4 L IS USM",
        "f_number": (4, 1),
        "shutter": (1, 125),
        "iso": 100,
        "focal_length": (24, 1),
        "exposure_program": 3,   # 光圈优先
        "metering_mode": 5,      # 评价测光
    },
    "索尼A7M4": {
        "make": "SONY",
        "model": "ILCE-7M4",
        "lens_make": "SONY",
        "lens_model": "FE 24-70mm F2.8 GM II",
        "f_number": (28, 10),    # F2.8
        "shutter": (1, 200),
        "iso": 100,
        "focal_length": (35, 1),
        "exposure_program": 3,
        "metering_mode": 5,
    },
    "尼康Z8": {
        "make": "NIKON CORPORATION",
        "model": "NIKON Z 8",
        "lens_make": "NIKON",
        "lens_model": "NIKKOR Z 24-70mm f/2.8 S",
        "f_number": (28, 10),
        "shutter": (1, 160),
        "iso": 64,
        "focal_length": (50, 1),
        "exposure_program": 3,
        "metering_mode": 5,
    },
}

DEFAULT_PRESET = "佳能R5"
