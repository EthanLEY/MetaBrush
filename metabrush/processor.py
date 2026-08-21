"""单文件处理：生成 EXIF、原子覆盖写入原图、恢复文件时间戳。

写入策略（防损坏）：
  绝不直接对原文件做「截断再写」。而是先在原图同目录写一个临时文件，
  完整写入并 flush+fsync 后，再用 os.replace 原子替换原文件 ——
  原文件要么保持完整旧内容，要么变成完整新内容，任何时刻都不会出现
  半截/空文件（进程被杀、断电、磁盘满、杀软拦截等中断均不影响原文件）。

时间戳策略（需求 5）：替换后通过 SetFileTime（Windows）或 os.utime（其它平台）
恢复原「创建时间 / 修改时间 / 访问时间」。
"""

import os
import random
import tempfile
from datetime import datetime
from typing import Optional, Tuple

import piexif

from . import jpeg_io, png_io
from .exif_builder import GPS_LAT_MAX, GPS_LAT_MIN, GPS_LON_MAX, GPS_LON_MIN, build_exif_dict
from .presets import PRESETS

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png"}
_JPG_EXTS = {".jpg", ".jpeg"}

# Windows FILETIME 纪元与 Unix 纪元的秒差
_UNIX_EPOCH_AS_FILETIME = 11644473600


def _image_size(path: str) -> Optional[Tuple[int, int]]:
    """读取图像宽高（失败时返回 None，不阻塞处理）。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
            return (int(w), int(h)) if w and h else None
    except Exception:
        return None


def _restore_times(path: str, st: os.stat_result) -> None:
    """恢复原「创建时间 / 修改时间 / 访问时间」。

    Windows 上用 SetFileTime 同时恢复三个时间（含创建时间）；
    其它平台用 os.utime（无法恢复创建时间，但该平台不涉及需求 5）。
    恢复失败只影响时间戳，不影响文件内容，故不抛出。
    """
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class _FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", wintypes.DWORD),
                            ("dwHighDateTime", wintypes.DWORD)]

            def _ns_to_ft(ns: int) -> _FILETIME:
                # st_*_ns 为 Unix 纪元纳秒；FILETIME 为 1601 纪元、单位 100ns
                v = ns // 100 + _UNIX_EPOCH_AS_FILETIME * 10_000_000
                return _FILETIME(v & 0xFFFFFFFF, (v >> 32) & 0xFFFFFFFF)

            GENERIC_WRITE = 0x40000000
            FILE_SHARE_READ = 0x1
            FILE_SHARE_WRITE = 0x2
            FILE_SHARE_DELETE = 0x4
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80

            CreateFileW = ctypes.windll.kernel32.CreateFileW
            CreateFileW.restype = wintypes.HANDLE
            CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.HANDLE]
            h = CreateFileW(path, GENERIC_WRITE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
            if h in (None, wintypes.HANDLE(-1).value):
                return
            try:
                ft_c = _ns_to_ft(st.st_ctime_ns)
                ft_a = _ns_to_ft(st.st_atime_ns)
                ft_m = _ns_to_ft(st.st_mtime_ns)
                ctypes.windll.kernel32.SetFileTime(
                    h, ctypes.byref(ft_c), ctypes.byref(ft_a), ctypes.byref(ft_m))
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        else:
            os.utime(path, (st.st_atime, st.st_mtime))
    except Exception:
        pass


def _write_atomic(path: str, new_data: bytes) -> None:
    """原子写回：同目录临时文件完整写入后 os.replace 替换原文件。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".metabrush_tmp_", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)      # 原子替换：原文件从不被截断
    except Exception:
        # 清理临时文件（若替换失败），原文件保持原样
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def process_file(path: str, preset_name: str,
                 now: Optional[datetime] = None,
                 rng: Optional[random.Random] = None) -> Tuple[bool, Optional[str]]:
    """处理单个文件，原子覆盖写回原图。

    返回 (True, None) 表示成功；(False, 原因) 表示可预期的失败。
    其它未预期异常直接抛出，由调用方记录并跳过。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        return False, f"不支持的文件类型“{ext}”，仅支持 .jpg/.jpeg/.png"
    if preset_name not in PRESETS:
        return False, f"未知预设“{preset_name}”"

    now = now or datetime.now()
    rng = rng or random

    # GPS：中国范围，每张图独立随机
    lat = rng.uniform(GPS_LAT_MIN, GPS_LAT_MAX)
    lon = rng.uniform(GPS_LON_MIN, GPS_LON_MAX)
    alt = int(rng.uniform(0, 500))

    exif_dict = build_exif_dict(PRESETS[preset_name], now, lat, lon,
                                image_size=_image_size(path), alt=alt)
    exif_bytes = piexif.dump(exif_dict)

    st = os.stat(path)
    with open(path, "rb") as f:
        data = f.read()

    try:
        if ext in _JPG_EXTS:
            new_data = jpeg_io.insert_exif(data, exif_bytes)
        else:
            # PNG eXIf 块不含 "Exif\0\0" 头
            new_data = png_io.insert_exif(data, exif_bytes[6:])
    except ValueError as e:          # 文件结构损坏等可预期错误
        return False, str(e)

    _write_atomic(path, new_data)    # 原子替换，原文件绝不出现半截状态

    # 恢复原「创建时间 / 修改时间 / 访问时间」
    _restore_times(path, st)
    return True, None
