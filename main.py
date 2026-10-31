# -*- coding: utf-8 -*-
"""
战舰世界 MOD 本地管理工具

1.自动检测游戏路径

2. 本地仓库管理
   - mod以ZIP格式导入，自动识别content、PnF
   - 对结构不完整的MOD压缩包，弹窗选择MOD类型，自动补全目录层级
   - MOD列表支持搜索（仅中文匹配）
   - MOD批量勾选安装
   - 支持删除本地仓库内的MOD压缩包

3. 区分MOD类型：content mod、PnF mod分别对应两套目录部署逻辑

4. 线上仓库
   - 从github、gitee拉取MOD清单，一键下载至本地仓库

5. 支持Inno‑Setup制作安装包

注意：
- 本工具仅做文件复制，不修改游戏本体程序
- 卸载前注意备份游戏mod相关文件，卸载同时会将本地仓库清空（工具自带的文件夹）
###仅供个人学习娱乐使用###
"""
import os
import sys
import json
import shutil
import zipfile
import threading
import urllib.request
import urllib.error
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


# ---------- 汉字拼音首字母（GB2312 一级字库区间） ----------
_GB_RANGES = [
    (0xB0A1, 0xB0CC, 'A'), (0xB0CD, 0xB2C1, 'B'), (0xB2C2, 0xB4ED, 'C'),
    (0xB4EE, 0xB6E9, 'D'), (0xB6EA, 0xB7A1, 'E'), (0xB7A2, 0xB8C0, 'F'),
    (0xB8C1, 0xB9FD, 'G'), (0xB9FE, 0xBBF9, 'H'), (0xBBFA, 0xBFA5, 'J'),
    (0xBFA6, 0xC0AB, 'K'), (0xC0AC, 0xC2E7, 'L'), (0xC2E8, 0xC4C2, 'M'),
    (0xC4C3, 0xC5B5, 'N'), (0xC5B6, 0xC5BD, 'O'), (0xC5BE, 0xC6D9, 'P'),
    (0xC6DA, 0xC8BA, 'Q'), (0xC8BB, 0xC8F5, 'R'), (0xC8F6, 0xCBF9, 'S'),
    (0xCBFA, 0xCDD9, 'T'), (0xCDDA, 0xCFA5, 'W'), (0xCFA6, 0xD1B8, 'X'),
    (0xD1B9, 0xD4D0, 'Y'), (0xD4D1, 0xD7F9, 'Z'),
]

def _first_letter(ch):
    if not ('\u4e00' <= ch <= '\u9fff'):
        return None
    try:
        gb = ch.encode('gb2312')
    except Exception:
        return None
    code = (gb[0] << 8) | gb[1]
    for lo, hi, letter in _GB_RANGES:
        if lo <= code <= hi:
            return letter
    return None


def _initials_of(name):
    letters = []
    for ch in name:
        fl = _first_letter(ch)
        if fl:
            letters.append(fl.lower())
        elif ch.isascii() and ch.isalpha():
            letters.append(ch.lower())
    return letters


def _match(name, query):
    q = query.strip().lower()
    if not q:
        return True
    if q in name.lower():
        return True
    init_str = ''.join(_initials_of(name))
    if q in init_str:
        return True
    if len(init_str) >= 2 and len(q) > 2:
        for start in range(len(init_str)):
            sub = init_str[start:]
            pos = 0
            matched = 0
            for c in sub:
                idx = q.find(c, pos)
                if idx == -1:
                    break
                matched += 1
                pos = idx + 1
            if matched >= 2:
                return True
    return False


# ---------- 目录结构 ----------
def _base_dir():
    """获取程序根目录（exe所在目录）"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def _data_dir():
    """数据目录：data/"""
    p = os.path.join(_base_dir(), "data")
    os.makedirs(p, exist_ok=True)
    return p

def _settings_dir():
    """配置目录：data/settings/"""
    p = os.path.join(_data_dir(), "settings")
    os.makedirs(p, exist_ok=True)
    return p

def _mods_dir():
    """MOD目录：data/mods/"""
    p = os.path.join(_data_dir(), "mods")
    os.makedirs(p, exist_ok=True)
    return p

def _uninstall_dir():
    """卸载目录：data/uninstall/"""
    p = os.path.join(_data_dir(), "uninstall")
    os.makedirs(p, exist_ok=True)
    return p

# ---------- 配置文件 ----------
def _config_path():
    return os.path.join(_settings_dir(), "config.json")


def _load_config():
    p = _config_path()
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_config(cfg: dict):
    p = _config_path()
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- 通用：解压ZIP到目标目录（自动清除顶层冗余文件夹） ----------
def _extract_zip_to_dir(zip_path: str, target_dir: str):
    """解压zip到target_dir，自动去掉顶层只有一个文件夹的冗余结构"""
    with zipfile.ZipFile(zip_path, 'r') as zf:
        all_names = []
        for info in zf.infolist():
            raw = info.filename
            try:
                fixed = raw.encode('cp437').decode('gbk')
            except Exception:
                fixed = raw
            all_names.append(fixed)

        # 检测是否所有文件都在同一个顶层文件夹下
        top_prefix = None
        for name in all_names:
            n = name.lstrip('/')
            if not n:
                continue
            parts = n.split('/')
            if len(parts) <= 1:
                top_prefix = None
                break
            if top_prefix is None:
                top_prefix = parts[0]
            elif parts[0] != top_prefix:
                top_prefix = None
                break

        for info in zf.infolist():
            raw_name = info.filename
            try:
                fixed_name = raw_name.encode('cp437').decode('gbk')
            except Exception:
                fixed_name = raw_name

            if top_prefix:
                fixed_name = fixed_name.lstrip('/')
                if fixed_name.startswith(top_prefix + '/'):
                    fixed_name = fixed_name[len(top_prefix) + 1:]

            if not fixed_name:
                continue
            if fixed_name.endswith('/'):
                os.makedirs(os.path.join(target_dir, fixed_name), exist_ok=True)
                continue
            target_path = os.path.join(target_dir, fixed_name)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with zf.open(info) as src, open(target_path, 'wb') as dst:
                shutil.copyfileobj(src, dst)


class ModCopyApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("visher MODs")
        root.geometry("620x650")
        root.minsize(620, 650)

        cfg = _load_config()
        self._config = cfg
        self.target_dir = tk.StringVar(value=cfg.get("target_dir", ""))
        self.oss_base_url = tk.StringVar(value="https://gitee.com/N23visher/korablimod")
        self.online_search_var = tk.StringVar()
        
        # 两个MOD列表的数据
        self.content_items = []
        self.content_check_vars = []
        self.pnf_items = []
        self.pnf_check_vars = []

        # 先定义方法，避免AttributeError
        self.delete_content = lambda: None
        self.delete_pnf = lambda: None
        self.set_all_content = lambda val: None
        self.set_all_pnf = lambda val: None
        
        self.online_items = []       # [{"name":..., "download_url":..., "size":...}]
        self.online_check_vars = []

        # 加载缓存的线上清单
        cache_path = os.path.join(_settings_dir(), "online_cache.json")
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    self.online_items = json.load(f)
                self.online_check_vars = [tk.BooleanVar(value=False) for _ in self.online_items]
            except Exception:
                pass

        self._build_ui()

        # 渲染缓存的线上清单
        if self.online_items:
            self._render_online_list()

        # 自动创建目录
        os.makedirs(os.path.join(_base_dir(), "content_mods"), exist_ok=True)
        os.makedirs(os.path.join(_base_dir(), "PnF_mods"), exist_ok=True)
        self.load_content_list()
        self.load_pnf_list()

        # 启动时自动后台刷新清单
        self.root.after(500, self._auto_refresh_online)

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, **pad)
        # 切换Tab时自动刷新本地仓库列表
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ===== Tab1: 本地仓库 =====
        tab_local = ttk.Frame(self.nb)
        self.nb.add(tab_local, text="  本地仓库  ")

        # 导入.zip文件
        frm_import = ttk.LabelFrame(tab_local, text="导入MOD")
        frm_import.pack(fill="x", **pad)
        ttk.Button(frm_import, text="选择.zip文件", command=self.import_zip).pack(side="left", padx=6, pady=6)
        ttk.Label(frm_import, text="选择后可自定义名称").pack(side="left", padx=10)
        ttk.Button(frm_import, text="刷新", command=self.refresh_all).pack(side="right", padx=6, pady=6)

        # 左右两栏：左边content，右边pnf
        list_frame = ttk.Frame(tab_local)
        list_frame.pack(fill="both", expand=True, **pad)

        # 左边：content mod
        frm_content = ttk.LabelFrame(list_frame, text="content mods")
        frm_content.pack(side="left", fill="y", expand=False, padx=(0, 2))
        frm_content.configure(width=290)
        frm_content.pack_propagate(False)

        # 定义空方法，避免AttributeError
        def delete_content():
            pass
        def delete_pnf():
            pass
        def set_all_content(val):
            pass
        def set_all_pnf(val):
            pass

        content_btn_bar = ttk.Frame(frm_content)
        content_btn_bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(content_btn_bar, text="全选", command=lambda: self.set_all_content(True)).pack(side="left", padx=3)
        ttk.Button(content_btn_bar, text="全不选", command=lambda: self.set_all_content(False)).pack(side="left", padx=3)
        ttk.Button(content_btn_bar, text="删除", command=self.delete_content).pack(side="left", padx=3)

        content_search = ttk.Frame(frm_content)
        content_search.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(content_search, text="搜索:").pack(side="left", padx=(0, 4))
        self.content_search_var = tk.StringVar()
        ttk.Entry(content_search, textvariable=self.content_search_var).pack(side="left", fill="x", expand=True)

        content_canvas = tk.Canvas(frm_content, highlightthickness=0)
        content_scroll = ttk.Scrollbar(frm_content, orient="vertical", command=content_canvas.yview)
        content_canvas.configure(yscrollcommand=content_scroll.set)
        content_scroll.pack(side="right", fill="y")
        content_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self.content_list_inner = ttk.Frame(content_canvas)
        self.content_list_inner.bind("<Configure>", lambda e: content_canvas.configure(scrollregion=content_canvas.bbox("all")))
        content_canvas.create_window((0, 0), window=self.content_list_inner, anchor="nw")

        # 右边：PnF mod
        frm_pnf = ttk.LabelFrame(list_frame, text="PnF mods")
        frm_pnf.pack(side="right", fill="y", expand=False, padx=(2, 0))
        frm_pnf.configure(width=290)
        frm_pnf.pack_propagate(False)

        pnf_btn_bar = ttk.Frame(frm_pnf)
        pnf_btn_bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(pnf_btn_bar, text="全选", command=lambda: self.set_all_pnf(True)).pack(side="left", padx=3)
        ttk.Button(pnf_btn_bar, text="全不选", command=lambda: self.set_all_pnf(False)).pack(side="left", padx=3)
        ttk.Button(pnf_btn_bar, text="删除", command=self.delete_pnf).pack(side="left", padx=3)

        pnf_search = ttk.Frame(frm_pnf)
        pnf_search.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(pnf_search, text="搜索:").pack(side="left", padx=(0, 4))
        self.pnf_search_var = tk.StringVar()
        ttk.Entry(pnf_search, textvariable=self.pnf_search_var).pack(side="left", fill="x", expand=True)

        pnf_canvas = tk.Canvas(frm_pnf, highlightthickness=0)
        pnf_scroll = ttk.Scrollbar(frm_pnf, orient="vertical", command=pnf_canvas.yview)
        pnf_canvas.configure(yscrollcommand=pnf_scroll.set)
        pnf_scroll.pack(side="right", fill="y")
        pnf_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))
        self.pnf_list_inner = ttk.Frame(pnf_canvas)
        self.pnf_list_inner.bind("<Configure>", lambda e: pnf_canvas.configure(scrollregion=pnf_canvas.bbox("all")))
        pnf_canvas.create_window((0, 0), window=self.pnf_list_inner, anchor="nw")

        # 游戏安装路径
        frm_dst = ttk.LabelFrame(tab_local, text="游戏安装路径")
        frm_dst.pack(fill="x", **pad)
        ttk.Entry(frm_dst, textvariable=self.target_dir).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(frm_dst, text="浏览…", command=self.pick_target).pack(side="left", padx=4)
        ttk.Button(frm_dst, text="自动检测", command=self.auto_detect_game).pack(side="left", padx=4)

        # 执行安装
        frm_run = ttk.Frame(tab_local)
        frm_run.pack(fill="x", **pad)
        self.btn_run = ttk.Button(frm_run, text="安装到游戏", command=self.start_copy)
        self.btn_run.pack(side="left", padx=6)
        self.btn_run.config(state="normal")
        self.progress = ttk.Progressbar(frm_run, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=6)

        self.status = ttk.Label(self.root, text="就绪", anchor="w")
        self.status.pack(fill="x", side="bottom")

        # ===== Table2: 线上仓库（OSS） =====
        tab_online = ttk.Frame(self.nb)
        self.nb.add(tab_online, text="  线上仓库  ")

        # 仓库选择
        frm_oss = ttk.LabelFrame(tab_online, text="来源仓库")
        frm_oss.pack(fill="x", **pad)

        self.source_var = tk.StringVar(value="github")
        ttk.Radiobutton(frm_oss, text="Gitee", variable=self.source_var, value="gitee", command=self._on_source_change).pack(side="left", padx=8, pady=6)
        ttk.Radiobutton(frm_oss, text="GitHub", variable=self.source_var, value="github", command=self._on_source_change).pack(side="left", padx=8, pady=6)
        ttk.Button(frm_oss, text="刷新", command=self.refresh_online).pack(side="left", padx=4)

        # 线上列表
        frm_online = ttk.LabelFrame(tab_online, text="mods列表")
        frm_online.pack(fill="both", expand=True, **pad)

        online_btn_bar = ttk.Frame(frm_online)
        online_btn_bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(online_btn_bar, text="全选", command=lambda: self._set_online_all(True)).pack(side="left", padx=3)
        ttk.Button(online_btn_bar, text="全不选", command=lambda: self._set_online_all(False)).pack(side="left", padx=3)

        online_search_bar = ttk.Frame(frm_online)
        online_search_bar.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(online_search_bar, text="搜索:").pack(side="left", padx=(0, 4))
        ttk.Entry(online_search_bar, textvariable=self.online_search_var).pack(side="left", fill="x", expand=True)
        self.online_search_var.trace_add("write", lambda *a: self._render_online_list())

        self.online_canvas = tk.Canvas(frm_online, highlightthickness=0)
        online_scroll = ttk.Scrollbar(frm_online, orient="vertical", command=self.online_canvas.yview)
        self.online_canvas.configure(yscrollcommand=online_scroll.set)
        online_scroll.pack(side="right", fill="y")
        self.online_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=(0, 6))

        def _on_mousewheel2(event):
            self.online_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.online_canvas.bind("<Enter>", lambda e: self.online_canvas.bind_all("<MouseWheel>", _on_mousewheel2))
        self.online_canvas.bind("<Leave>", lambda e: self.online_canvas.unbind_all("<MouseWheel>"))

        self.online_list_inner = ttk.Frame(self.online_canvas)
        self.online_list_inner.bind(
            "<Configure>", lambda e: self.online_canvas.configure(scrollregion=self.online_canvas.bbox("all"))
        )
        self.online_canvas.create_window((0, 0), window=self.online_list_inner, anchor="nw")

        # 下载按钮
        frm_dl = ttk.Frame(tab_online)
        frm_dl.pack(fill="x", **pad)
        self.btn_dl = ttk.Button(frm_dl, text="下载", command=self.download_selected_online)
        self.btn_dl.pack(side="left", padx=6)
        self.online_progress = ttk.Progressbar(frm_dl, mode="determinate")
        self.online_progress.pack(side="left", fill="x", expand=True, padx=6)

        ttk.Label(tab_online, text="说明：下载完成后请到本地仓库安装MOD").pack(anchor="w", padx=10, pady=(0, 6))

        # ===== Tab3: 卸载本软件 =====
        tab_uninstall = ttk.Frame(self.nb)
        self.nb.add(tab_uninstall, text="  卸载本软件  ")

        ttk.Label(tab_uninstall, text="").pack(pady=40)
        ttk.Label(tab_uninstall, text="卸载 visher Content MOD", font=("Microsoft YaHei", 14, "bold")).pack(pady=10)
        ttk.Label(tab_uninstall, text="").pack(pady=10)
        ttk.Button(tab_uninstall, text="点击卸载", command=self.uninstall_app).pack(pady=20, ipadx=20, ipady=10)

    # ---------- 本地仓库事件 ----------
    def _ask_mod_name(self, prompt, default=""):
        # 输入MOD名称
        dlg = tk.Toplevel(self.root)
        dlg.title("MOD 名称")
        dlg.geometry("450x180")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()

        ttk.Label(dlg, text=prompt, font=("Microsoft YaHei", 11)).pack(pady=(20, 10))
        entry = ttk.Entry(dlg, font=("Microsoft YaHei", 11), width=40)
        entry.pack(pady=5, padx=20, fill="x")
        entry.insert(0, default)
        entry.focus_set()
        entry.select_range(0, tk.END)

        result = [None]

        def on_ok():
            result[0] = entry.get().strip()
            dlg.destroy()

        def on_cancel():
            dlg.destroy()

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=15)
        ttk.Button(btn_frame, text="确定", command=on_ok).pack(side="left", padx=10, ipadx=10)
        ttk.Button(btn_frame, text="取消", command=on_cancel).pack(side="left", padx=10, ipadx=10)

        entry.bind("<Return>", lambda e: on_ok())
        entry.bind("<Escape>", lambda e: on_cancel())

        self.root.wait_window(dlg)
        return result[0]

    def pick_root(self):
        messagebox.showinfo("提示", "自动管理目录：content_mods和PnF_mods")

    def auto_detect_game(self):
        """自动检测游戏路径，找\游戏根目录\bin\最大数字\res_mods"""
        # 先看看配置里有没有保存的bin路径
        bin_path = self._config.get("game_bin_path", "")
        if bin_path and os.path.isdir(bin_path):
            # 有了直接用
            pass
        else:
            # 自动搜索常见游戏路径
            bin_path = self._search_common_game_paths()
            if not bin_path:
                # 找不到，让用户手动选
                d = filedialog.askdirectory(title="未找到游戏，请手动选择战舰世界的bin文件夹\n（如：D:\Games\WorldOfWarships\bin）")
                if not d:
                    return
                bin_path = d
            self._config["game_bin_path"] = bin_path
            self._persist()

        # 找bin下面数字最大的文件夹
        try:
            dirs = []
            for name in os.listdir(bin_path):
                full = os.path.join(bin_path, name)
                if os.path.isdir(full) and name.isdigit():
                    dirs.append((int(name), full))
            if not dirs:
                messagebox.showwarning("提示", f"在 {bin_path} 里没找到数字版本目录\n请确认这是战舰世界的bin文件夹")
                return
            # 找最大的数字
            dirs.sort(reverse=True)
            max_version_dir = dirs[0][1]
            # 找res_mods
            res_mods = os.path.join(max_version_dir, "res_mods")
            if not os.path.isdir(res_mods):
                # 如果没有res_mods，就用max_version_dir
                res_mods = max_version_dir
            self.target_dir.set(res_mods)
            self.status.config(text=f"已自动检测游戏路径：{res_mods}")
        except Exception as e:
            messagebox.showerror("错误", f"自动检测失败：{e}")

    def _search_common_game_paths(self):
        """自动搜索常见游戏安装路径"""
        # 常见的exe路径列表
        exe_paths = [
            # Korabli
            r"C:\Program Files\Korabli\Korabli.exe",
            r"D:\Program Files\Korabli\Korabli.exe",
            r"C:\Program Files (x86)\Korabli\Korabli.exe",
            r"D:\Program Files (x86)\Korabli\Korabli.exe",
            r"C:\Games\Korabli\Korabli.exe",
            r"D:\Games\Korabli\Korabli.exe",
            r"E:\Games\Korabli\Korabli.exe",
            r"D:\Korabli\Korabli.exe",
            r"E:\Korabli\Korabli.exe",
            # WorldOfWarships
            r"C:\Program Files\World_of_Warships\WorldOfWarships.exe",
            r"C:\Program Files (x86)\World_of_Warships\WorldOfWarships.exe",
            r"D:\Program Files\World_of_Warships\WorldOfWarships.exe",
            r"D:\Program Files (x86)\World_of_Warships\WorldOfWarships.exe",
            r"D:\Games\World_of_Warships\WorldOfWarships.exe",
            r"D:\Games\WorldOfWarships\WorldOfWarships.exe",
            r"E:\Games\World_of_Warships\WorldOfWarships.exe",
            r"D:\World_of_Warships\WorldOfWarships.exe",
            r"E:\World_of_Warships\WorldOfWarships.exe",
            r"C:\Games\World_of_Warships\WorldOfWarships.exe",
            # 360国服（能装mod吗？）
            r"D:\Games\Wargaming.net\World_of_Warships_CN360\WorldOfWarships.exe",
            r"C:\Games\Wargaming.net\World_of_Warships_CN360\WorldOfWarships.exe",
        ]
        for exe_path in exe_paths:
            if os.path.isfile(exe_path):
                # 找到exe程序，自动找同目录下的bin
                game_dir = os.path.dirname(exe_path)
                bin_path = os.path.join(game_dir, "bin")
                if os.path.isdir(bin_path):
                    return bin_path

        # 常见的bin路径
        common_paths = [
            r"D:\Games\Korabli\bin",
            r"D:\Korabli\bin",
            r"D:\Games\WorldOfWarships\bin",
            r"D:\Games\Wargaming.net\WorldOfWarships\bin",
        ]
        for path in common_paths:
            if os.path.isdir(path):
                return path
        
        # 没找到
        return None

    def pick_target(self):
        d = filedialog.askdirectory(title="选择目标路径")
        if d:
            self.target_dir.set(d)

    def _ask_mod_type_dialog(self):
        """自定义对话框，选择MOD类型"""
        result = [None]
        dlg = tk.Toplevel(self.root)
        dlg.title("无法识别MOD类型")
        dlg.geometry("300x120")
        dlg.transient(self.root)
        dlg.grab_set()
        
        ttk.Label(dlg, text="无法识别MOD类型\n\n请选择导入到哪个目录：").pack(pady=10)
        
        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(pady=10)
        
        def select_content():
            result[0] = "content"
            dlg.destroy()
        
        def select_pnf():
            result[0] = "pnf"
            dlg.destroy()
        
        ttk.Button(btn_frame, text="content mod", command=select_content).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="PnF mod", command=select_pnf).pack(side="left", padx=10)
        
        self.root.wait_window(dlg)
        return result[0]

    def import_zip(self):
        path = filedialog.askopenfilename(
            title="选择 MOD ZIP 文件",
            filetypes=[("ZIP 压缩包", "*.zip")]
        )
        if not path:
            return

        # 自动检测zip里面是content还是PnF
        mod_type = None
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                has_content = any("content/" in n for n in names)
                has_pnf = any("PnFMods/" in n for n in names)
                if has_content:
                    mod_type = "content"
                elif has_pnf:
                    mod_type = "pnf"
        except Exception:
            pass

        # 检测不到，弹窗提问
        need_fix_structure = False
        if mod_type is None:
            need_fix_structure = True
            # 对话框
            mod_type = self._ask_mod_type_dialog()

        if mod_type == "content":
            root = os.path.join(_base_dir(), "content_mods")
            mod_type_name = "Content MOD"
            sub_dir_name = "content"
        else:
            root = os.path.join(_base_dir(), "PnF_mods")
            mod_type_name = "PnF MOD"
            sub_dir_name = "PnFMods"

        default_name = os.path.splitext(os.path.basename(path))[0]
        mod_name = self._ask_mod_name(f"输入 {mod_type_name} 名称：", default_name)
        if not mod_name:
            return
        mod_name = mod_name.strip()
        if not mod_name:
            return

        target_zip = os.path.join(root, mod_name + ".zip")
        if os.path.exists(target_zip):
            if not messagebox.askyesno("确认", f"文件已存在：\n{target_zip}\n是否覆盖？"):
                return

        try:
            if need_fix_structure:
                # 检测不成功目录结构，重新打包
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    # 解压原zip到临时目录
                    with zipfile.ZipFile(path, "r") as zf:
                        zf.extractall(tmpdir)
                    
                    # 检查临时目录里是不是只有一层与mod_name同名
                    # 如果：是；去掉那一层
                    items = os.listdir(tmpdir)
                    if len(items) == 1 and os.path.isdir(os.path.join(tmpdir, items[0])) and items[0] == mod_name:
                        # 只有一层同名文件夹，进去拿内容
                        inner_dir = os.path.join(tmpdir, items[0])
                        # 创建新的zip，把内容放到正确的目录结构里
                        # 结构：zip\mod_name\PnFMods\原内容（去掉重复的那一层）
                        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                            for root_dir, dirs, files in os.walk(inner_dir):
                                for file in files:
                                    file_path = os.path.join(root_dir, file)
                                    rel_path = os.path.relpath(file_path, inner_dir)
                                    new_path = os.path.join(mod_name, sub_dir_name, rel_path)
                                    zf.write(file_path, new_path)
                    else:
                        # 如果：否；直接打包
                        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                            for root_dir, dirs, files in os.walk(tmpdir):
                                for file in files:
                                    file_path = os.path.join(root_dir, file)
                                    rel_path = os.path.relpath(file_path, tmpdir)
                                    new_path = os.path.join(mod_name, sub_dir_name, rel_path)
                                    zf.write(file_path, new_path)
            else:
                # 检测成功目录结构，直接复制
                shutil.copy2(path, target_zip)
            
            if mod_type == "content":
                self.load_content_list()
            else:
                self.load_pnf_list()
            
            if need_fix_structure:
                # 提示用户检查弹窗
                messagebox.showwarning("导入完成", f"已导入到 {mod_type_name}：\n{target_zip}\n\n由于原文件路径不完整，已自动创建目录结构。\n请前往 {root} 检查MOD内容是否正确。")
            else:
                messagebox.showinfo("完成", f"已导入到 {mod_type_name}：\n{target_zip}")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def refresh_all(self):
        """刷新所有列表"""
        self.load_content_list()
        self.load_pnf_list()

    def load_content_list(self):
        root = os.path.join(_base_dir(), "content_mods")
        if not os.path.isdir(root):
            os.makedirs(root, exist_ok=True)

        try:
            names = sorted(
                os.path.splitext(n)[0] for n in os.listdir(root)
                if n.lower().endswith(".zip") and os.path.isfile(os.path.join(root, n))
            )
        except Exception as e:
            messagebox.showerror("错误", f"读取content_mods目录失败：{e}")
            return

        self.content_items = names
        self.content_check_vars = [tk.BooleanVar(value=False) for _ in names]
        self._render_content_list()

    def load_pnf_list(self):
        root = os.path.join(_base_dir(), "PnF_mods")
        if not os.path.isdir(root):
            os.makedirs(root, exist_ok=True)

        try:
            names = sorted(
                os.path.splitext(n)[0] for n in os.listdir(root)
                if n.lower().endswith(".zip") and os.path.isfile(os.path.join(root, n))
            )
        except Exception as e:
            messagebox.showerror("错误", f"读取PnF_mods目录失败：{e}")
            return

        self.pnf_items = names
        self.pnf_check_vars = [tk.BooleanVar(value=False) for _ in names]
        self._render_pnf_list()

    def _render_content_list(self):
        for w in self.content_list_inner.winfo_children():
            w.destroy()

        q = self.content_search_var.get().strip().lower()
        if not self.content_items:
            ttk.Label(self.content_list_inner, text="（暂无）").pack(anchor="w", padx=8, pady=8)
            return

        shown = 0
        for n, var in zip(self.content_items, self.content_check_vars):
            if q and q not in n.lower():
                continue
            shown += 1
            text = n

            row = ttk.Frame(self.content_list_inner)
            row.pack(anchor="w", fill="x", padx=4, pady=1)

            cb = ttk.Checkbutton(row, variable=var)
            cb.pack(side="left")
            lbl = ttk.Label(row, text=text)
            lbl.pack(side="left", padx=4)

            def _toggle(e, v=var):
                v.set(not v.get())
            row.bind("<Button-1>", _toggle)
            lbl.bind("<Button-1>", _toggle)
            row.bind("<Enter>", lambda e: row.configure(cursor="hand2"))
            row.bind("<Leave>", lambda e: row.configure(cursor=""))

        if shown == 0:
            ttk.Label(self.content_list_inner, text="无匹配MOD").pack(anchor="w", padx=8, pady=8)

    def _render_pnf_list(self):
        for w in self.pnf_list_inner.winfo_children():
            w.destroy()

        q = self.pnf_search_var.get().strip().lower()
        if not self.pnf_items:
            ttk.Label(self.pnf_list_inner, text="（暂无）").pack(anchor="w", padx=8, pady=8)
            return

        shown = 0
        for n, var in zip(self.pnf_items, self.pnf_check_vars):
            if q and q not in n.lower():
                continue
            shown += 1
            text = n

            row = ttk.Frame(self.pnf_list_inner)
            row.pack(anchor="w", fill="x", padx=4, pady=1)

            cb = ttk.Checkbutton(row, variable=var)
            cb.pack(side="left")
            lbl = ttk.Label(row, text=text)
            lbl.pack(side="left", padx=4)

            def _toggle(e, v=var):
                v.set(not v.get())
            row.bind("<Button-1>", _toggle)
            lbl.bind("<Button-1>", _toggle)
            row.bind("<Enter>", lambda e: row.configure(cursor="hand2"))
            row.bind("<Leave>", lambda e: row.configure(cursor=""))

        if shown == 0:
            ttk.Label(self.pnf_list_inner, text="无匹配MOD").pack(anchor="w", padx=8, pady=8)

    def set_all_content(self, val: bool):
        q = self.content_search_var.get().strip().lower()
        for n, var in zip(self.content_items, self.content_check_vars):
            if not q or q in n.lower():
                var.set(val)

    def set_all_pnf(self, val: bool):
        q = self.pnf_search_var.get().strip().lower()
        for n, var in zip(self.pnf_items, self.pnf_check_vars):
            if not q or q in n.lower():
                var.set(val)

    def delete_content(self):
        root = os.path.join(_base_dir(), "content_mods")
        selected = [n for n, v in zip(self.content_items, self.content_check_vars) if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请先勾选要删除的content mod")
            return
        if not messagebox.askyesno("确认", f"确定要删除 {len(selected)} 个Content MOD吗？\n此操作不可撤销！"):
            return
        ok, fail = 0, 0
        for name in selected:
            zip_path = os.path.join(root, name + ".zip")
            try:
                os.remove(zip_path)
                ok += 1
            except Exception:
                fail += 1
        self.load_content_list()

    def delete_pnf(self):
        root = os.path.join(_base_dir(), "PnF_mods")
        selected = [n for n, v in zip(self.pnf_items, self.pnf_check_vars) if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请先勾选要删除的PnF mod")
            return
        if not messagebox.askyesno("确认", f"确定要删除 {len(selected)} 个PnF MOD吗？\n此操作不可撤销！"):
            return
        ok, fail = 0, 0
        for name in selected:
            zip_path = os.path.join(root, name + ".zip")
            try:
                os.remove(zip_path)
                ok += 1
            except Exception:
                fail += 1
        self.load_pnf_list()

    def rename_mod(self):
        # 暂时不支持改名
        messagebox.showinfo("提示", "暂时不支持改名")
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        old_path = os.path.join(root, old_name + ".zip")
        new_path = os.path.join(root, new_name + ".zip")
        if os.path.exists(new_path):
            messagebox.showwarning("提示", f"已存在同名MOD：{new_name}")
            return
        try:
            os.rename(old_path, new_path)
            self.status.config(text=f"已改名：{old_name} → {new_name}")
            self.load_content_list()
        except Exception as e:
            messagebox.showerror("改名失败", str(e))

    # ---------- 复制 ----------
    def start_copy(self):
        target = self.target_dir.get().strip()
        if not target:
            messagebox.showwarning("提示", "请选择目标路径")
            return

        # 收集选中的content和pnf MOD
        content_selected = [n for n, v in zip(self.content_items, self.content_check_vars) if v.get()]
        pnf_selected = [n for n, v in zip(self.pnf_items, self.pnf_check_vars) if v.get()]
        
        if not content_selected and not pnf_selected:
            messagebox.showwarning("提示", "请至少勾选一个 MOD")
            return

        self._persist()
        os.makedirs(target, exist_ok=True)
        self.btn_run.config(state="disabled")
        total = len(content_selected) + len(pnf_selected)
        self.progress.config(maximum=total, value=0)

        t = threading.Thread(target=self._copy_worker, args=(target, content_selected, pnf_selected), daemon=True)
        t.start()

    def _copy_worker(self, target, content_selected, pnf_selected):
        ok, fail = [], []
        
        # 安装content MOD
        if content_selected:
            root = os.path.join(_base_dir(), "content_mods")
            dst_root = os.path.join(target, "content")
            os.makedirs(dst_root, exist_ok=True)
            for name in content_selected:
                zip_path = os.path.join(root, name + ".zip")
                try:
                    if not os.path.isfile(zip_path):
                        fail.append(f"{name}：找不到zip文件")
                        continue
                    
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with zipfile.ZipFile(zip_path, "r") as zf:
                            zf.extractall(tmpdir)
                        
                        src = None
                        for dirpath, dirnames, filenames in os.walk(tmpdir):
                            if os.path.basename(dirpath) == "content":
                                src = dirpath
                                break
                        
                        if not src:
                            fail.append(f"{name}：无 content 子目录")
                            continue
                        
                        for entry in os.listdir(src):
                            s = os.path.join(src, entry)
                            d = os.path.join(dst_root, entry)
                            if os.path.isdir(s):
                                shutil.copytree(s, d, dirs_exist_ok=True)
                            else:
                                shutil.copy2(s, d)
                    
                    ok.append(name)
                except Exception as e:
                    fail.append(f"{name}：{e}")

        # 安装pnf MOD
        if pnf_selected:
            root = os.path.join(_base_dir(), "PnF_mods")
            dst_root = os.path.join(target, "PnFMods")
            os.makedirs(dst_root, exist_ok=True)
            for name in pnf_selected:
                zip_path = os.path.join(root, name + ".zip")
                try:
                    if not os.path.isfile(zip_path):
                        fail.append(f"{name}：找不到zip文件")
                        continue
                    
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmpdir:
                        with zipfile.ZipFile(zip_path, "r") as zf:
                            zf.extractall(tmpdir)
                        
                        src = None
                        for dirpath, dirnames, filenames in os.walk(tmpdir):
                            if os.path.basename(dirpath) == "PnFMods":
                                src = dirpath
                                break
                        
                        if not src:
                            fail.append(f"{name}：无 PnFMods 子目录")
                            continue
                        
                        for entry in os.listdir(src):
                            s = os.path.join(src, entry)
                            d = os.path.join(dst_root, entry)
                            if os.path.isdir(s):
                                shutil.copytree(s, d, dirs_exist_ok=True)
                            else:
                                shutil.copy2(s, d)
                    
                    ok.append(name)
                except Exception as e:
                    fail.append(f"{name}：{e}")

        # 统计总进度
        total = len(ok) + len(fail)
        self.root.after(0, self._copy_done, ok, fail)

    def _update_progress(self, i, total, cur):
        self.progress.config(value=i)
        self.status.config(text=f"正在复制 ({i}/{total})：{cur}")

    def _copy_done(self, ok, fail):
        self.btn_run.config(state="normal")
        msg = f"完成：成功 {len(ok)} 个，失败/跳过 {len(fail)} 个"
        self.status.config(text=msg)
        detail = ""
        if fail:
            detail = "\n\n失败/跳过明细：\n" + "\n".join(fail)
        messagebox.showinfo("结束", msg + detail)

    # ---------- Gitee仓库 ----------
    def _on_mod_type_change(self):
        # 2.0版本不需要切换MOD类型，左右两栏同时显示
        pass

    def _on_tab_changed(self, event):
        # 切换到本地仓库Tab时，延迟刷新一次列表
        current_tab = self.nb.index(self.nb.select())
        if current_tab == 0:
            # 取消之前的刷新，避免重复
            if hasattr(self, '_refresh_after_id'):
                self.root.after_cancel(self._refresh_after_id)
            # 延迟100ms刷新，让界面先响应
            self._refresh_after_id = self.root.after(100, lambda: (self.load_content_list(), self.load_pnf_list()))

    def uninstall_app(self):
        """卸载本软件"""
        if not messagebox.askyesno("确认", "确定要卸载 visher Content MOD 吗？"):
            return
        unins_path = os.path.join(_uninstall_dir(), "unins000.exe")
        if os.path.isfile(unins_path):
            os.startfile(unins_path)
            self.root.destroy()
        else:
            messagebox.showwarning("提示", "找不到卸载程序，请手动删除文件夹")

    def _on_source_change(self):
        """切换来源仓库时自动刷新"""
        self.refresh_online()

    def _get_current_repo(self):
        """根据选择的来源返回 (platform, owner, repo)"""
        source = self.source_var.get()
        if source == "github":
            return "github", "N23visher", "korablimod"
        else:
            return "gitee", "N23visher", "korablimod"

    def _parse_gitee_repo(self):
        """返回当前选择的仓库 (owner, repo)，失败返回None"""
        source, owner, repo = self._get_current_repo()
        return owner, repo

    def _auto_refresh_online(self):
        """启动时后台静默刷新，不弹窗"""
        repo_info = self._parse_gitee_repo()
        if not repo_info:
            return
        t = threading.Thread(target=self._auto_refresh_worker, args=(repo_info,), daemon=True)
        t.start()

    def _fetch_mods_list(self, owner, repo):
        """用API列mods目录，支持Gitee和GitHub"""
        platform, _, _ = self._get_current_repo()

        if platform == "github":
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/mods"
            raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/master/mods"
        else:
            api_url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/contents/mods"
            raw_base = f"https://gitee.com/{owner}/{repo}/raw/master/mods"

        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list):
                return [], "api_error"
            mods = []
            for item in data:
                if item.get("type") != "file":
                    continue
                fname = item.get("name", "")
                if not fname.lower().endswith(".zip"):
                    continue
                mod_name = os.path.splitext(fname)[0]
                # 补全download_url
                download_url = item.get("download_url", "")
                if not download_url:
                    download_url = f"{raw_base}/{fname}"
                mods.append({
                    "name": mod_name,
                    "download_url": download_url,
                })
            return mods, platform
        except Exception as e:
            return [], f"error: {e}"

    def _auto_refresh_worker(self, repo_info):
        owner, repo = repo_info
        mods, source = self._fetch_mods_list(owner, repo)
        if not mods:
            return

        # 静默更新
        def _update():
            self.online_items = mods
            self.online_check_vars = [tk.BooleanVar(value=False) for _ in mods]
            self._render_online_list()
            platform_label = "GitHub" if source == "github" else "Gitee"
            self.status.config(text=f"线上共 {len(mods)} 个MOD（{platform_label}，已自动刷新）")
            # 保存缓存
            cache_path = os.path.join(_settings_dir(), "online_cache.json")
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(mods, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        self.root.after(0, _update)

    def refresh_online(self):
        repo_info = self._parse_gitee_repo()
        if not repo_info:
            messagebox.showwarning("提示", "请输入有效的Gitee仓库地址，如：\nhttps://gitee.com/用户名/仓库名")
            return

        self.btn_dl.config(state="disabled")
        platform, _, _ = self._get_current_repo()
        platform_label = "GitHub" if platform == "github" else "Gitee"
        self.status.config(text=f"正在拉取{platform_label}仓库清单…")

        t = threading.Thread(target=self._refresh_online_worker, args=(repo_info,), daemon=True)
        t.start()

    def _refresh_online_worker(self, repo_info):
        owner, repo = repo_info
        mods, source = self._fetch_mods_list(owner, repo)

        if not mods:
            self.root.after(0, self._on_refresh_done, f"拉取失败：{source}", 0)
            return

        self.online_items = mods
        self.online_check_vars = [tk.BooleanVar(value=False) for _ in mods]

        # 保存缓存
        cache_path = os.path.join(_settings_dir(), "online_cache.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(mods, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        platform_label = "GitHub" if source == "github" else "Gitee"
        self.root.after(0, self._on_refresh_done, None, len(mods), platform_label)

    def _on_refresh_done(self, err_msg, count, platform_label=None):
        self.btn_dl.config(state="normal")
        self._render_online_list()
        if err_msg:
            self.status.config(text=f"拉取失败（已显示缓存清单）：{err_msg}")
        else:
            self.status.config(text=f"线上共 {count} 个MOD（{platform_label}）")

    def _render_online_list(self):
        for w in self.online_list_inner.winfo_children():
            w.destroy()

        q = self.online_search_var.get().strip()
        if not self.online_items:
            ttk.Label(self.online_list_inner, text="（暂无线上MOD，请先刷新清单）").pack(anchor="w", padx=8, pady=8)
            return

        shown = 0
        for item, var in zip(self.online_items, self.online_check_vars):
            name = item.get("name", "")
            if q and q not in name.lower():
                continue
            shown += 1
            text = name

            row = ttk.Frame(self.online_list_inner)
            row.pack(anchor="w", fill="x", padx=4, pady=1)

            cb = ttk.Checkbutton(row, variable=var)
            cb.pack(side="left")
            lbl = ttk.Label(row, text=text)
            lbl.pack(side="left", padx=4)

            def _toggle(e, v=var):
                v.set(not v.get())
            row.bind("<Button-1>", _toggle)
            lbl.bind("<Button-1>", _toggle)
            row.bind("<Enter>", lambda e: row.configure(cursor="hand2"))
            row.bind("<Leave>", lambda e: row.configure(cursor=""))
            lbl.bind("<Enter>", lambda e: row.configure(cursor="hand2"))
            lbl.bind("<Leave>", lambda e: row.configure(cursor=""))

        if shown == 0:
            ttk.Label(self.online_list_inner, text="（无匹配MOD）").pack(anchor="w", padx=8, pady=8)

    def _set_online_all(self, val: bool):
        q = self.online_search_var.get()
        for item, var in zip(self.online_items, self.online_check_vars):
            if _match(item.get("name", ""), q):
                var.set(val)

    def download_selected_online(self):
        repo_info = self._parse_gitee_repo()
        if not repo_info:
            messagebox.showwarning("提示", "请先输入有效的仓库地址")
            return

        root = os.path.join(_base_dir(), "content_mods")
        os.makedirs(root, exist_ok=True)

        selected = [item for item, v in zip(self.online_items, self.online_check_vars) if v.get()]
        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个MOD")
            return

        self.btn_dl.config(state="disabled")
        self.online_progress.config(maximum=len(selected), value=0)
        self._persist()

        t = threading.Thread(target=self._download_worker, args=(root, selected), daemon=True)
        t.start()

    def _download_worker(self, local_root, selected):
        ok, fail = [], []
        # 保存最新进度和状态
        self._download_progress = {"done": 0, "total": len(selected), "current_name": "", "done_flag": False}

        def download_one(item):
            name = item.get("name", "")
            download_url = item.get("download_url", "")
            if not name or not download_url:
                return ("fail", name, "缺少下载链接")

            target_zip = os.path.join(local_root, name + ".zip")

            try:
                # 下载zip
                from urllib.parse import urlparse, quote
                parsed = urlparse(download_url)
                encoded_path = quote(parsed.path)
                encoded_url = f"{parsed.scheme}://{parsed.netloc}{encoded_path}"
                if parsed.query:
                    encoded_url += f"?{parsed.query}"

                req = urllib.request.Request(encoded_url, headers={"User-Agent": "ModCopyTool/1.0"})
                with urllib.request.urlopen(req, timeout=120) as resp, open(target_zip, "wb") as f:
                    shutil.copyfileobj(resp, f)

                # 检查文件是否为空
                file_size = os.path.getsize(target_zip)
                if file_size > 1024:  # 大于1KB
                    return ("ok", name, None)
                else:
                    return ("fail", name, f"下载的文件太小（{file_size}字节），可能损坏")
            except Exception as e:
                return ("fail", name, str(e))

        # 启动UI定时器，每隔100ms读一次进度变量
        self._start_download_timer()

        try:
            # 单线程下载
            for item in selected:
                status, name, err = download_one(item)
                self._download_progress["done"] += 1
                self._download_progress["current_name"] = name
                if status == "ok":
                    ok.append(name)
                else:
                    fail.append(f"{name}：{err}")
        except Exception as e:
            fail.append(f"下载过程出错：{str(e)}")
        finally:
            # 标记完成
            self._download_progress["done_flag"] = True
            # 停止定时器，显示最终结果
            if hasattr(self, "_download_timer_id"):
                self.root.after_cancel(self._download_timer_id)
            self.btn_dl.config(state="normal")
            self.online_progress.config(value=len(selected))
            msg = f"下载完成：成功 {len(ok)} 个，失败 {len(fail)} 个"
            if fail:
                msg += "（失败：" + "、".join(fail) + "）"
            self.status.config(text=msg)

    def _start_download_timer(self):
        """定时器刷新进度"""
        def update():
            if not self._download_progress["done_flag"]:
                done = self._download_progress["done"]
                total = self._download_progress["total"]
                name = self._download_progress["current_name"]
                self.online_progress.config(value=done)
                self.status.config(text=f"下载中 ({done}/{total})：{name}")
                self._download_timer_id = self.root.after(100, update)
        update()

    # ---------- 配置 ----------
    def _persist(self):
        _save_config({
            "target_dir": self.target_dir.get().strip(),
            "game_bin_path": self._config.get("game_bin_path", ""),
        })

    def _on_close(self):
        self._persist()
        self.root.destroy()
        # 强制退出
        import os
        os._exit(0)


if __name__ == "__main__":
    import sys
    win = tk.Tk()
    # 窗口图标
    try:
        if getattr(sys, 'frozen', False):
            # 打包exe后路径
            icon_path = os.path.join(sys._MEIPASS, "app.ico")
        else:
            # 开发路径
            icon_path = os.path.join(os.path.dirname(__file__), "app.ico")
        if os.path.exists(icon_path):
            win.iconbitmap(icon_path)
    except Exception:
        pass
    app = ModCopyApp(win)
    win.mainloop()
