"""MetaBrush - EXIF 元数据批量处理工具（CustomTkinter GUI）。

启动：python main.py
"""

import os
import queue
import threading
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from metabrush.presets import DEFAULT_PRESET, PRESETS
from metabrush.processor import process_file

APP_TITLE = "MetaBrush"
APP_SUBTITLE = "EXIF 元数据批量处理"
FILE_TYPES = [("图片文件", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")]

COLORS = {
    "info": "#8a94a6",
    "success": "#2ecc71",
    "error": "#ff5252",
    "system": "#4da6ff",
    "warn": "#ffc107",
}


def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


class MetaBrushApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("780x660")
        self.minsize(700, 580)

        self.files: list = []
        self.running: bool = False
        self._queue: queue.Queue = queue.Queue()
        self._file_rows: list = []

        self.protocol("WM_DELETE_WINDOW", self._on_close)   # 处理中关闭窗口需确认

        self._build_ui()
        self._render_files()
        self._update_count()

    def _on_close(self):
        if self.running:
            ok = messagebox.askyesno(
                "正在处理",
                "仍有图片正在处理，中途退出可能中断写入。\n确定要退出吗？")
            if not ok:
                return
        self.destroy()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)   # 文件列表区可伸缩

        # 顶部：标题 + 已选数量
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(20, 6))
        header.grid_columnconfigure(1, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text=APP_TITLE,
                     font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text=APP_SUBTITLE,
                     font=ctk.CTkFont(size=12), text_color=COLORS["info"]).pack(anchor="w")

        self.count_badge = ctk.CTkLabel(
            header, text="已选择 0 张图片", corner_radius=14, height=30, width=160,
            fg_color=("gray82", "gray25"), text_color=("gray15", "gray92"),
            font=ctk.CTkFont(size=13, weight="bold"))
        self.count_badge.grid(row=0, column=1, sticky="e")

        # 控制行：预设下拉框 + 添加文件 + 清空
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=26, pady=8)
        controls.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(controls, text="预设", font=ctk.CTkFont(size=13)).grid(
            row=0, column=0, padx=(0, 8))
        self.preset_combo = ctk.CTkComboBox(
            controls, values=list(PRESETS.keys()), width=170, height=34,
            font=ctk.CTkFont(size=13), state="readonly")
        self.preset_combo.set(DEFAULT_PRESET)
        self.preset_combo.grid(row=0, column=1, padx=(0, 10))

        self.add_button = ctk.CTkButton(
            controls, text="＋ 添加文件", width=116, height=34, corner_radius=8,
            font=ctk.CTkFont(size=13, weight="bold"), command=self._on_add_files)
        self.add_button.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.clear_button = ctk.CTkButton(
            controls, text="清空列表", width=92, height=34, corner_radius=8,
            fg_color="transparent", border_width=1,
            font=ctk.CTkFont(size=13), command=self._on_clear)
        self.clear_button.grid(row=0, column=3)

        # 文件列表
        self.file_list = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.file_list.grid(row=2, column=0, sticky="nsew", padx=26, pady=8)
        self._empty_hint = ctk.CTkLabel(
            self.file_list,
            text="点击「添加文件」选择图片\n仅处理选中的 .jpg / .jpeg / .png，不遍历子文件夹\n双击列表项可移除",
            text_color=COLORS["info"], font=ctk.CTkFont(size=13), justify="center")
        self._empty_hint.pack(pady=34)

        # 底部：进度条 + 状态 + 开始按钮
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="sew", padx=26, pady=(4, 10))
        bottom.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(bottom, height=10, corner_radius=5)
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(bottom, text="就绪", text_color=COLORS["info"],
                                         font=ctk.CTkFont(size=12))
        self.status_label.grid(row=1, column=0, sticky="w")

        self.start_button = ctk.CTkButton(
            bottom, text="开始处理", width=150, height=38, corner_radius=8,
            fg_color="#2ecc71", hover_color="#27ae60", text_color="white",
            font=ctk.CTkFont(size=14, weight="bold"), command=self._on_start)
        self.start_button.grid(row=1, column=2, sticky="e")

        # 彩色日志
        self.log_box = ctk.CTkTextbox(self, height=150, corner_radius=10,
                                      font=ctk.CTkFont(family="Consolas", size=12),
                                      wrap="word")
        self.log_box.grid(row=4, column=0, sticky="ew", padx=26, pady=(0, 14))
        for name, color in COLORS.items():
            self.log_box.tag_config(name, foreground=color)
        self.log_box.configure(state="disabled")
        self._log("system", f"{APP_TITLE} 已就绪，请添加图片并选择预设。")

    # ---------------- 文件列表 ----------------
    def _render_files(self):
        for w in self._file_rows:
            w.destroy()
        self._file_rows = []
        if not self.files:
            self._empty_hint.pack(pady=34)
            return
        self._empty_hint.pack_forget()
        for i, path in enumerate(self.files):
            row = ctk.CTkFrame(self.file_list, corner_radius=8,
                               fg_color=("gray86", "gray17"))
            row.pack(fill="x", pady=3, padx=2)
            row.grid_columnconfigure(2, weight=1)

            ext = Path(path).suffix.lower().lstrip(".").upper() or "?"
            size = os.path.getsize(path) if os.path.exists(path) else 0

            ctk.CTkLabel(row, text=f"{i + 1:>3}", width=40, text_color=COLORS["info"],
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(10, 4), pady=7)
            ctk.CTkLabel(row, text=ext, width=52, corner_radius=8,
                         fg_color=("#dce8ff", "#22334d"), text_color=("#2b5bd7", "#7ea6ff"),
                         font=ctk.CTkFont(size=11, weight="bold")
                         ).grid(row=0, column=1, padx=(0, 6))
            ctk.CTkLabel(row, text=os.path.basename(path), anchor="w",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=2, sticky="ew", padx=4)
            ctk.CTkLabel(row, text=_fmt_size(size), width=84, text_color=COLORS["info"],
                         font=ctk.CTkFont(size=12)).grid(row=0, column=3, padx=(4, 10))

            row.bind("<Double-Button-1>", lambda e, p=path: self._remove_file(p))
            self._file_rows.append(row)

    def _update_count(self):
        n = len(self.files)
        self.count_badge.configure(text=f"已选择 {n} 张图片")
        if not self.running:
            self.start_button.configure(state="normal" if n else "disabled")

    def _on_add_files(self):
        if self.running:
            return
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=FILE_TYPES)
        added = 0
        for p in paths:
            norm = os.path.normcase(os.path.abspath(p))
            if norm not in self.files:
                self.files.append(norm)
                added += 1
        if added:
            self._render_files()
            self._update_count()
            self._log("info", f"已添加 {added} 张图片，当前共 {len(self.files)} 张。")

    def _remove_file(self, path):
        if self.running:
            return
        norm = os.path.normcase(os.path.abspath(path))
        if norm in self.files:
            self.files.remove(norm)
            self._render_files()
            self._update_count()
            self._log("info", f"已移除：{os.path.basename(path)}")

    def _on_clear(self):
        if self.running:
            return
        self.files.clear()
        self._render_files()
        self._update_count()
        self._log("info", "已清空文件列表。")

    # ---------------- 处理 ----------------
    def _on_start(self):
        if self.running or not self.files:
            return
        preset = self.preset_combo.get()
        files = list(self.files)
        self._set_running(True)
        self.progress.set(0)
        self.status_label.configure(text="处理中…")
        self._log("system", f"开始处理：共 {len(files)} 张图片，预设「{preset}」")
        # 非守护线程：即使窗口被关闭，也会把当前批次全部处理完（配合原子写入，
        # 任何中断都不会让文件停留在半截状态）
        t = threading.Thread(target=self._worker, args=(files, preset))
        t.start()
        self.after(80, self._poll_queue)

    def _worker(self, files, preset):
        total = len(files)
        ok = fail = 0
        for i, path in enumerate(files):
            base = os.path.basename(path)
            try:
                success, err = process_file(path, preset)
                if success:
                    ok += 1
                    self._post(("success", f"[{i + 1}/{total}] {base}  ✓ 处理成功"))
                else:
                    fail += 1
                    self._post(("error", f"[{i + 1}/{total}] {base}  ✗ {err}"))
            except Exception as e:   # 需求 8：跳过并标红，继续下一个
                fail += 1
                self._post(("error", f"[{i + 1}/{total}] {base}  ✗ 异常：{e}"))
            self._post(("progress", (i + 1, total)))
        self._post(("done", (ok, fail)))

    def _post(self, item):
        self._queue.put(item)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    i, total = payload
                    self.progress.set(i / total if total else 0)
                    self.status_label.configure(text=f"处理中… {i}/{total}")
                elif kind == "done":
                    ok, fail = payload
                    self.progress.set(1)
                    self._set_running(False)
                    self.status_label.configure(text="完成")
                    self._log("system", f"处理完成：成功 {ok} 张，失败 {fail} 张")
                    if fail:
                        self._log("warn", "存在失败项，请查看上方红色日志。")
                    messagebox.showinfo("处理完成", f"成功 {ok} 张，失败 {fail} 张")
                    return
                else:
                    self._log(kind, payload)
        except queue.Empty:
            pass
        if self.running:
            self.after(80, self._poll_queue)

    def _set_running(self, running):
        self.running = running
        if running:
            self.add_button.configure(state="disabled")
            self.clear_button.configure(state="disabled")
            self.preset_combo.configure(state="disabled")
            self.start_button.configure(state="disabled")
        else:
            self.add_button.configure(state="normal")
            self.clear_button.configure(state="normal")
            self.preset_combo.configure(state="readonly")
            self.start_button.configure(state="normal" if self.files else "disabled")

    def _log(self, kind, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", kind)
        self.log_box.configure(state="disabled")
        self.log_box.see("end")


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = MetaBrushApp()
    app.mainloop()


if __name__ == "__main__":
    main()
