# MetaBrush

EXIF 元数据批量处理工具（Windows 桌面应用）。基于 Python 3.10 + CustomTkinter，
打包为单文件 EXE（PyInstaller `-F -w`）。

## 功能一览

| 需求 | 实现 |
| --- | --- |
| 环境 | Python 3.10 + CustomTkinter，依赖仅 `customtkinter` / `pillow` / `piexif`，PyInstaller 单 EXE（`-F -w`） |
| UI | 扁平化深色界面：顶部已选数量徽标，中部预设下拉框（佳能R5 / 索尼A7M4 / 尼康Z8）与「添加文件」，底部进度条 + 彩色日志 |
| 预设模板 | 自动填充 Make、Model、LensMake、LensModel、Aperture(FNumber+ApertureValue)、ShutterSpeed(ExposureTime+ShutterSpeedValue)、ISO、FocalLength 等 EXIF 字段 |
| 拍摄时间 | DateTimeOriginal / DateTimeDigitized（及 DateTime）自动设为处理时刻的系统时间，无手动输入框 |
| 文件日期 | 覆盖写回后恢复原「修改时间/访问时间」；Windows 上就地写回不重建文件，「创建时间」绝对不变 |
| GPS | 随机生成，限定中国范围（纬度 18–54N、经度 73–135E），每张图独立随机（含随机海拔与 GPS 时间戳） |
| 处理 | 直接覆盖原图；仅处理选中的 `.jpg/.jpeg/.png`，不遍历子文件夹 |
| 异常 | 单张失败即跳过并红色日志，继续处理下一张；文件结构异常（非法长度/标记、截断、缺少 SOS/EOI/IEND）一律**跳过且不修改原文件**，绝不写出被截断的图片；写入中途失败会恢复原文件 |
| 打包 | `build.bat` 一键打包并在桌面创建/覆盖快捷方式「MetaBrush」 |

## 目录结构

```
MetaBrush/
├─ main.py                  # GUI 入口（CustomTkinter）
├─ metabrush/
│  ├─ presets.py            # 三套相机预设模板
│  ├─ exif_builder.py       # 构建 EXIF 字典（时间/GPS/预设字段）
│  ├─ jpeg_io.py            # JPEG APP1(Exif) 段写入（无重压缩）
│  ├─ png_io.py             # PNG eXIf 块写入（无重压缩）
│  └─ processor.py          # 单文件处理 + 时间戳恢复
├─ tests/test_core.py       # 核心逻辑无界面测试（24 项）
├─ requirements.txt
├─ build.ps1 / build.bat    # 一键打包 + 桌面快捷方式
└─ README.md
```

## 开发运行

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

运行测试：

```bat
.venv\Scripts\python -m unittest discover -s tests -v
```

## 一键打包（生成桌面快捷方式）

双击 `build.bat`（或 `powershell -ExecutionPolicy Bypass -File build.ps1`）。
脚本将：

1. 创建 `.venv` 并安装依赖（含 PyInstaller）；
2. 运行核心逻辑测试，未通过则中止；
3. `PyInstaller --onefile --windowed` 打包为 `dist\MetaBrush.exe`；
4. 在桌面创建快捷方式「MetaBrush」（指向 EXE，已存在则覆盖）。

## 说明

- 预设字段会**整体替换**原 EXIF（含旧拍摄时间、旧 GPS、旧机身信息、Software 等），
  **新写入的元数据不包含软件名 MetaBrush**。
- **原图元数据清洗**（防 AI 溯源）：
  - PNG：只保留 IHDR 基础信息（宽高/位深/色彩类型/压缩/滤波/隔行）与图像数据，
    删除 `prompt` / `workflow` / `AICG` / `parameters` / `Description` 等所有附属
    元数据块（tEXt / zTXt / iTXt / eXIf / tIME / gAMA / pHYs 等一律不保留）；
    仅额外保留渲染必需的 PLTE（调色板）、tRNS（透明）与未知关键块。
  - JPEG：删除 XMP（APP1）与 COM 注释段（AI 信息常见载体），并整体替换 EXIF；
    图像数据原样保留，不经重新编码。
- EXIF 时间取处理时刻（本地时间）；GPS 时间戳取处理时刻的 UTC 时间。
- PNG 的 EXIF 写为规范 eXIf 块（数据为不含 `Exif\0\0` 头的原始 TIFF 数据），
  且**严格插入在 IHDR 之后**（PNG 规范要求 IHDR 必须是第一个块，否则严格校验工具会判为损坏）。
- JPEG/PNG 解析是**严格**的：只要无法完整、合法地解析文件结构，就跳过该文件，
  不会对原文件做任何改动（防止把结构有瑕疵、但查看器仍可显示的图片写坏）。
- 打包机建议使用 Python 3.10–3.12（PyInstaller 对 3.13/3.14 的支持取决于其版本）。
- `requirements.txt` 将 customtkinter 锁定在 `>=5.2,<6.0`：6.0.0 在 PyInstaller
  冻结环境下存在窗口无法显示的缺陷（打包时请勿使用 6.x）。
