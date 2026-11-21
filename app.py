"""PDF 분할기 — 큰 PDF 를 원하는 페이지에서 잘라 주는 창 프로그램."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitter as S  # noqa: E402

try:
    from PIL import Image, ImageTk  # type: ignore
except Exception:
    Image = ImageTk = None
try:
    import pypdfium2 as pdfium  # type: ignore
except Exception:
    pdfium = None
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES  # type: ignore
except Exception:
    TkinterDnD = None
    DND_FILES = None

APP_NAME = "PDF 분할기"
VERSION = "1.0.0"

# ------------------------------------------------------------------ 색/글꼴
BG = "#F3F4FA"
CARD = "#FFFFFF"
BORDER = "#E4E6F1"
TEXT = "#1C1E2B"
MUTED = "#8187A2"
ACCENT = "#6C5CE7"
ACCENT_D = "#5646D8"
ACCENT_SOFT = "#EFECFF"
FIELD = "#F8F8FD"
OK = "#1FAF84"
WARN = "#E8634A"

if sys.platform == "win32":
    FONT = "Malgun Gothic"
elif sys.platform == "darwin":
    FONT = "Apple SD Gothic Neo"
else:
    FONT = "Noto Sans CJK KR"


def f(size, weight="normal"):
    return (FONT, size, weight)


def rrect(c: tk.Canvas, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


# ------------------------------------------------------------------ 위젯
class RoundButton(tk.Canvas):
    STYLES = {
        "primary": (ACCENT, ACCENT_D, "#FFFFFF"),
        "soft": (ACCENT_SOFT, "#E2DDFF", ACCENT_D),
        "ghost": (CARD, "#F1F2F8", TEXT),
        "danger": ("#FDECE8", "#FADBD3", WARN),
    }

    def __init__(self, parent, text, command=None, kind="primary", width=120,
                 height=38, font=None, radius=12, k=1.0):
        bg = parent.cget("bg")
        w, h = int(width * k), int(height * k)
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2")
        self.w, self.h, self.r = w, h, int(radius * k)
        self.command = command
        self.kind = kind
        self.text = text
        self.font = font or f(10, "bold")
        self.enabled = True
        self.hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _colors(self):
        base, hov, fg = self.STYLES[self.kind]
        if not self.enabled:
            return "#ECEDF3", "#B3B7C9"
        return (hov if self.hover else base), fg

    def _draw(self):
        self.delete("all")
        fill, fg = self._colors()
        outline = BORDER if self.kind == "ghost" and self.enabled else fill
        rrect(self, 1, 1, self.w - 1, self.h - 1, self.r, fill=fill, outline=outline)
        self.create_text(self.w / 2, self.h / 2, text=self.text, fill=fg, font=self.font)

    def _set_hover(self, v):
        self.hover = v
        self._draw()

    def _click(self, _e):
        if self.enabled and self.command:
            self.command()

    def configure_button(self, text=None, kind=None, enabled=None):
        if text is not None:
            self.text = text
        if kind is not None:
            self.kind = kind
        if enabled is not None:
            self.enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
        self._draw()


class ProgressBar(tk.Canvas):
    def __init__(self, parent, height=10, k=1.0):
        super().__init__(parent, height=int(height * k), bg=parent.cget("bg"),
                         highlightthickness=0, bd=0)
        self.frac = 0.0
        self.color = ACCENT
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, frac, color=None):
        self.frac = max(0.0, min(1.0, frac))
        if color:
            self.color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        rrect(self, 0, 0, w, h, h / 2, fill="#E8E9F3", outline="#E8E9F3")
        if self.frac > 0:
            x = max(h, w * self.frac)
            rrect(self, 0, 0, x, h, h / 2, fill=self.color, outline=self.color)


class Segmented(tk.Frame):
    def __init__(self, parent, options, command, k=1.0):
        super().__init__(parent, bg="#EEEFF7", padx=int(4 * k), pady=int(4 * k))
        self.command = command
        self.labels = []
        self.value = 0
        for i, name in enumerate(options):
            lb = tk.Label(self, text=name, font=f(10, "bold"), bg="#EEEFF7", fg=MUTED,
                          padx=int(12 * k), pady=int(7 * k), cursor="hand2")
            lb.grid(row=0, column=i, sticky="nsew", padx=int(2 * k))
            self.columnconfigure(i, weight=1)
            lb.bind("<Button-1>", lambda e, i=i: self.select(i))
            self.labels.append(lb)
        self.select(0, fire=False)

    def select(self, i, fire=True):
        self.value = i
        for j, lb in enumerate(self.labels):
            if j == i:
                lb.configure(bg=CARD, fg=ACCENT_D)
            else:
                lb.configure(bg="#EEEFF7", fg=MUTED)
        if fire:
            self.command(i)


def card(parent, k, **grid):
    fr = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER,
                  padx=int(18 * k), pady=int(16 * k))
    if grid:
        fr.grid(**grid)
    return fr


def entry(parent, var, width=10, k=1.0, justify="left"):
    e = tk.Entry(parent, textvariable=var, width=width, font=f(11), bg=FIELD, fg=TEXT,
                 relief="flat", highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=ACCENT, insertbackground=ACCENT, justify=justify)
    e.configure(bd=int(6 * k))
    return e


# ------------------------------------------------------------------ 앱
class App:
    MODES = ("페이지 지정", "쪽 수로", "용량 기준")

    def __init__(self, root: tk.Tk):
        self.root = root
        try:
            self.k = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except Exception:
            self.k = 1.0
        k = self.k
        root.title(f"{APP_NAME}  v{VERSION}")
        root.configure(bg=BG)
        root.geometry(f"{int(1040 * k)}x{int(720 * k)}")
        root.minsize(int(940 * k), int(660 * k))
        ico = os.path.join(HERE, "icon.ico")
        if sys.platform == "win32" and os.path.exists(ico):
            try:
                root.iconbitmap(ico)
            except Exception:
                pass

        self.src: S.PdfSource | None = None
        self.doc = None          # pdfium 미리보기용
        self.thumb = None
        self.page_var = tk.StringVar(value="1")
        self.preview_page = 1
        self.out_dir = ""
        self.out_custom = False
        self.ranges = []
        self.plan_error = ""
        self.running = False
        self.cancel_flag = False
        self.q: queue.Queue = queue.Queue()
        self.last_out = ""

        self.spec_var = tk.StringVar()
        self.every_var = tk.StringVar(value="100")
        self.count_var = tk.StringVar(value="2")
        self.sub_mode = tk.IntVar(value=0)  # 0: N쪽씩, 1: N개로
        self.mb_var = tk.StringVar(value="100")
        for v in (self.spec_var, self.every_var, self.count_var, self.mb_var):
            v.trace_add("write", lambda *a: self.update_plan())
        self.sub_mode.trace_add("write", lambda *a: self.update_plan())

        self._style()
        self._build()
        self.mode = 0
        self.show_mode(0)
        self.update_plan()
        self.root.after(80, self._poll)
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
            self.root.after(200, lambda: self.load(sys.argv[1]))

    # ---------------------------------------------------------- 스타일
    def _style(self):
        k = self.k
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Parts.Treeview", background=CARD, fieldbackground=CARD,
                     foreground=TEXT, rowheight=int(30 * k), font=f(10), borderwidth=0,
                     relief="flat")
        st.configure("Parts.Treeview.Heading", background="#F6F6FB", foreground=MUTED,
                     font=f(9, "bold"), relief="flat", borderwidth=0, padding=(6, 6))
        st.map("Parts.Treeview.Heading", background=[("active", "#EFEFF8")])
        st.map("Parts.Treeview", background=[("selected", ACCENT_SOFT)],
               foreground=[("selected", ACCENT_D)])
        st.layout("Parts.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Slim.Vertical.TScrollbar", troughcolor=CARD, background="#DADCE8",
                     bordercolor=CARD, arrowcolor=MUTED, gripcount=0, relief="flat")

    # ---------------------------------------------------------- 화면
    def _build(self):
        k = self.k
        root = self.root
        pad = int(22 * k)
        wrap = tk.Frame(root, bg=BG, padx=pad, pady=int(18 * k))
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(0, weight=0, minsize=int(380 * k))
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(2, weight=1)

        # 머리말
        head = tk.Frame(wrap, bg=BG)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, int(14 * k)))
        logo = tk.Canvas(head, width=int(42 * k), height=int(42 * k), bg=BG,
                         highlightthickness=0)
        rrect(logo, 0, 0, 42 * k, 42 * k, 12 * k, fill=ACCENT, outline=ACCENT)
        logo.create_text(21 * k, 21 * k, text="✂", fill="white", font=f(17, "bold"))
        logo.pack(side="left")
        tt = tk.Frame(head, bg=BG)
        tt.pack(side="left", padx=int(12 * k))
        tk.Label(tt, text=APP_NAME, font=f(18, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(tt, text="너무 커서 안 올라가는 PDF, 원하는 곳에서 깔끔하게 잘라요",
                 font=f(10), bg=BG, fg=MUTED).pack(anchor="w")
        self.engine_lbl = tk.Label(head, text="", font=f(9), bg=BG, fg=MUTED)
        self.engine_lbl.pack(side="right", anchor="s")

        # 파일 카드 (드롭 영역)
        self.drop = tk.Frame(wrap, bg=CARD, highlightthickness=2,
                             highlightbackground="#D9D4FB", cursor="hand2")
        self.drop.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, int(14 * k)))
        inner = tk.Frame(self.drop, bg=CARD, padx=int(20 * k), pady=int(14 * k))
        inner.pack(fill="x")
        self.doc_icon = tk.Canvas(inner, width=int(44 * k), height=int(52 * k), bg=CARD,
                                  highlightthickness=0)
        self._draw_doc_icon(False)
        self.doc_icon.pack(side="left")
        txt = tk.Frame(inner, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, padx=int(14 * k))
        self.file_title = tk.Label(txt, text="PDF 파일을 여기로 끌어 놓거나, 클릭해서 고르세요",
                                   font=f(12, "bold"), bg=CARD, fg=TEXT, anchor="w")
        self.file_title.pack(fill="x")
        hint = "700MB 넘는 큰 파일도 괜찮아요" + ("" if TkinterDnD else "  (클릭해서 고르기)")
        self.file_sub = tk.Label(txt, text=hint, font=f(10), bg=CARD, fg=MUTED, anchor="w")
        self.file_sub.pack(fill="x")
        self.pick_btn = RoundButton(inner, "파일 고르기", self.pick_file, kind="soft",
                                    width=112, height=36, k=k)
        self.pick_btn.pack(side="right")
        for w in (self.drop, inner, txt, self.file_title, self.file_sub, self.doc_icon):
            w.bind("<Button-1>", lambda e: self.pick_file())
        if TkinterDnD is not None:
            for w in (self.root, self.drop):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                    w.dnd_bind("<<DropEnter>>", lambda e: self._drop_hl(True))
                    w.dnd_bind("<<DropLeave>>", lambda e: self._drop_hl(False))
                except Exception:
                    pass

        # 왼쪽: 설정 카드
        left = card(wrap, k, row=2, column=0, sticky="nsew", padx=(0, int(14 * k)))
        left.columnconfigure(0, weight=1)
        tk.Label(left, text="어떻게 나눌까요?", font=f(12, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=0, sticky="w")
        self.seg = Segmented(left, self.MODES, self.show_mode, k=k)
        self.seg.grid(row=1, column=0, sticky="ew", pady=(int(10 * k), int(14 * k)))
        self.mode_area = tk.Frame(left, bg=CARD)
        self.mode_area.grid(row=2, column=0, sticky="nsew")
        self.mode_area.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        self.panels = [self._panel_spec(), self._panel_count(), self._panel_size()]

        tk.Frame(left, bg=BORDER, height=1).grid(row=3, column=0, sticky="ew",
                                                 pady=int(12 * k))
        outrow = tk.Frame(left, bg=CARD)
        outrow.grid(row=4, column=0, sticky="ew")
        outrow.columnconfigure(0, weight=1)
        tk.Label(outrow, text="저장 위치", font=f(10, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=0, sticky="w")
        self.out_lbl = tk.Label(outrow, text="파일을 고르면 원본 옆에 새 폴더로 저장돼요",
                                font=f(9), bg=CARD, fg=MUTED, anchor="w", justify="left",
                                wraplength=int(250 * k))
        self.out_lbl.grid(row=1, column=0, sticky="w", pady=(int(2 * k), 0))
        RoundButton(outrow, "바꾸기", self.pick_out, kind="ghost", width=70, height=32,
                    font=f(9, "bold"), k=k).grid(row=0, column=1, rowspan=2, sticky="e")

        # 오른쪽: 미리보기 + 조각 목록
        right = card(wrap, k, row=2, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(1, weight=1)
        tk.Label(right, text="미리보기", font=f(12, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=0, sticky="w")
        self.summary = tk.Label(right, text="", font=f(10, "bold"), bg=CARD, fg=ACCENT_D)
        self.summary.grid(row=0, column=1, sticky="e")

        pv = tk.Frame(right, bg=CARD)
        pv.grid(row=1, column=0, sticky="ns", pady=(int(10 * k), 0), padx=(0, int(16 * k)))
        self.thumb_w, self.thumb_h = int(210 * k), int(280 * k)
        self.thumb_cv = tk.Canvas(pv, width=self.thumb_w, height=self.thumb_h, bg="#F4F4F9",
                                  highlightthickness=1, highlightbackground=BORDER)
        self.thumb_cv.pack()
        self._thumb_placeholder()
        nav = tk.Frame(pv, bg=CARD)
        nav.pack(fill="x", pady=(int(8 * k), 0))
        RoundButton(nav, "◀", lambda: self.goto(self.preview_page - 1), kind="ghost",
                    width=36, height=32, k=k).pack(side="left")
        pe = entry(nav, self.page_var, width=5, k=k, justify="center")
        pe.pack(side="left", padx=int(6 * k), fill="y")
        pe.bind("<Return>", lambda e: self._goto_entry())
        pe.bind("<FocusOut>", lambda e: self._goto_entry())
        self.page_total_lbl = tk.Label(nav, text="/ -", font=f(10), bg=CARD, fg=MUTED)
        self.page_total_lbl.pack(side="left")
        RoundButton(nav, "▶", lambda: self.goto(self.preview_page + 1), kind="ghost",
                    width=36, height=32, k=k).pack(side="right")
        self.cut_btn = RoundButton(pv, "✂  이 쪽 뒤에서 자르기", self.cut_here, kind="soft",
                                   width=210, height=36, k=k)
        self.cut_btn.pack(pady=(int(8 * k), 0))
        for w in (self.thumb_cv,):
            w.bind("<Enter>", lambda e: self.thumb_cv.focus_set())
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-4>", lambda e: self.goto(self.preview_page - 1))
            w.bind("<Button-5>", lambda e: self.goto(self.preview_page + 1))

        tbl = tk.Frame(right, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        tbl.grid(row=1, column=1, sticky="nsew", pady=(int(10 * k), 0))
        tbl.rowconfigure(0, weight=1)
        tbl.columnconfigure(0, weight=1)
        cols = ("no", "pages", "count", "size")
        self.tree = ttk.Treeview(tbl, columns=cols, show="headings", style="Parts.Treeview",
                                 selectmode="browse")
        for c, name, w, anc in (("no", "#", 46, "center"), ("pages", "페이지", 150, "w"),
                                ("count", "쪽 수", 70, "e"), ("size", "용량", 110, "e")):
            self.tree.heading(c, text=name, anchor=anc)
            self.tree.column(c, width=int(w * k), anchor=anc, stretch=(c == "pages"))
        self.tree.tag_configure("odd", background="#FBFBFE")
        self.tree.tag_configure("big", foreground=WARN)
        self.tree.tag_configure("done", foreground=OK)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(tbl, orient="vertical", command=self.tree.yview,
                           style="Slim.Vertical.TScrollbar")
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_row)
        self.tree_note = tk.Label(right, text="", font=f(9), bg=CARD, fg=MUTED, anchor="w",
                                  justify="left")
        self.tree_note.grid(row=2, column=1, sticky="ew", pady=(int(6 * k), 0))

        # 아래: 진행 + 실행
        bottom = tk.Frame(wrap, bg=BG)
        bottom.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(int(16 * k), 0))
        bottom.columnconfigure(0, weight=1)
        stat = tk.Frame(bottom, bg=BG)
        stat.grid(row=0, column=0, sticky="ew", padx=(0, int(16 * k)))
        self.status = tk.Label(stat, text="PDF 를 먼저 골라 주세요", font=f(10), bg=BG,
                               fg=MUTED, anchor="w")
        self.status.pack(fill="x")
        self.bar = ProgressBar(stat, height=10, k=k)
        self.bar.pack(fill="x", pady=(int(6 * k), 0))
        self.open_btn = RoundButton(bottom, "폴더 열기", self.open_folder, kind="ghost",
                                    width=100, height=46, k=k)
        self.open_btn.grid(row=0, column=1, padx=(0, int(10 * k)))
        self.open_btn.configure_button(enabled=False)
        self.go_btn = RoundButton(bottom, "분할 시작  ▶", self.start, kind="primary",
                                  width=170, height=46, font=f(12, "bold"), k=k)
        self.go_btn.grid(row=0, column=2)
        self.go_btn.configure_button(enabled=False)

        eng = []
        eng.append("빠른 엔진 pikepdf" if S.pikepdf is not None else "기본 엔진 pypdf")
        if not (pdfium and ImageTk):
            eng.append("미리보기 꺼짐")
        self.engine_lbl.configure(text=" · ".join(eng))

    # 모드별 입력 패널 -------------------------------------------------
    def _hint(self, parent, text, row):
        tk.Label(parent, text=text, font=f(9), bg=CARD, fg=MUTED, justify="left",
                 anchor="w", wraplength=int(330 * self.k)
                 ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(int(8 * self.k), 0))

    def _panel_spec(self):
        k = self.k
        p = tk.Frame(self.mode_area, bg=CARD)
        p.columnconfigure(0, weight=1)
        tk.Label(p, text="몇 쪽 뒤에서 자를까요?", font=f(10, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=0, sticky="w", pady=(0, int(6 * k)))
        e = entry(p, self.spec_var, width=28, k=k)
        e.grid(row=1, column=0, sticky="ew")
        self.spec_entry = e
        self._hint(p, "• 100, 250  →  1~100 / 101~250 / 251~끝, 3개로 잘라요\n"
                      "• 1-100, 300-400  →  적은 구간만 뽑아요\n"
                      "• 오른쪽 미리보기에서 ‘이 쪽 뒤에서 자르기’를 눌러도 돼요", 2)
        return p

    def _panel_count(self):
        k = self.k
        p = tk.Frame(self.mode_area, bg=CARD)
        p.columnconfigure(2, weight=1)
        for i, (label, var, unit) in enumerate((("한 조각에", self.every_var, "쪽씩"),
                                                ("똑같이", self.count_var, "개로 나누기"))):
            rb = tk.Radiobutton(p, text=label, variable=self.sub_mode, value=i, font=f(10),
                                bg=CARD, fg=TEXT, activebackground=CARD, selectcolor=CARD,
                                highlightthickness=0, bd=0, cursor="hand2")
            rb.grid(row=i, column=0, sticky="w", pady=int(4 * k))
            e = entry(p, var, width=7, k=k, justify="center")
            e.grid(row=i, column=1, padx=int(8 * k), pady=int(4 * k))
            e.bind("<FocusIn>", lambda ev, i=i: self.sub_mode.set(i))
            tk.Label(p, text=unit, font=f(10), bg=CARD, fg=TEXT).grid(row=i, column=2,
                                                                      sticky="w")
        self._hint(p, "마지막 조각은 남은 쪽 수만큼만 들어가요.", 2)
        return p

    def _panel_size(self):
        k = self.k
        p = tk.Frame(self.mode_area, bg=CARD)
        p.columnconfigure(2, weight=1)
        tk.Label(p, text="조각 하나를 최대", font=f(10, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=0, sticky="w")
        entry(p, self.mb_var, width=7, k=k, justify="center").grid(row=0, column=1,
                                                                   padx=int(8 * k))
        tk.Label(p, text="MB 이하로", font=f(10, "bold"), bg=CARD, fg=TEXT
                 ).grid(row=0, column=2, sticky="w")
        chips = tk.Frame(p, bg=CARD)
        chips.grid(row=1, column=0, columnspan=3, sticky="w", pady=(int(10 * k), 0))
        for mb in (25, 50, 100, 200, 500):
            RoundButton(chips, f"{mb}MB", lambda mb=mb: self.mb_var.set(str(mb)), kind="ghost",
                        width=58, height=30, font=f(9, "bold"), radius=15, k=k
                        ).pack(side="left", padx=(0, int(6 * k)))
        self._hint(p, "업로드 용량 제한에 딱 맞출 때 좋아요. 조각을 실제로 만들어 보면서 "
                      "크기를 맞추기 때문에 다른 방식보다 조금 더 걸려요.\n"
                      "오른쪽 목록은 대략적인 예상이에요.", 2)
        return p

    def show_mode(self, i):
        self.mode = i
        for j, p in enumerate(self.panels):
            if j == i:
                p.grid(row=0, column=0, sticky="nsew")
            else:
                p.grid_forget()
        self.update_plan()

    # ---------------------------------------------------------- 파일
    def _draw_doc_icon(self, loaded):
        c, k = self.doc_icon, self.k
        c.delete("all")
        col = ACCENT if loaded else "#B9B0F7"
        w, h, fold = 40 * k, 50 * k, 12 * k
        x0, y0 = 2 * k, 1 * k
        c.create_polygon(x0, y0, x0 + w - fold, y0, x0 + w, y0 + fold, x0 + w, y0 + h,
                         x0, y0 + h, fill=ACCENT_SOFT, outline=col, width=max(1, int(2 * k)))
        c.create_polygon(x0 + w - fold, y0, x0 + w - fold, y0 + fold, x0 + w, y0 + fold,
                         fill=col, outline=col)
        c.create_text(x0 + w / 2, y0 + h * 0.64, text="PDF", fill=col, font=f(8, "bold"))

    def _drop_hl(self, on):
        self.drop.configure(highlightbackground=ACCENT if on else "#D9D4FB")

    def _on_drop(self, event):
        self._drop_hl(False)
        try:
            files = self.root.tk.splitlist(event.data)
        except Exception:
            files = [event.data]
        pdfs = [x for x in files if x.lower().endswith(".pdf")]
        if not pdfs:
            messagebox.showwarning(APP_NAME, "PDF 파일만 넣을 수 있어요.")
            return
        self.load(pdfs[0])

    def pick_file(self):
        if self.running:
            return
        path = filedialog.askopenfilename(title="나눌 PDF 고르기",
                                          filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")])
        if path:
            self.load(path)

    def pick_out(self):
        if self.running:
            return
        d = filedialog.askdirectory(title="저장할 폴더 고르기",
                                    initialdir=os.path.dirname(self.out_dir) if self.out_dir else None)
        if d:
            self.out_dir = d
            self.out_custom = True
            self._show_out()

    def _show_out(self):
        self.out_lbl.configure(text=self.out_dir or "-", fg=TEXT if self.out_dir else MUTED)

    def load(self, path):
        if self.running:
            return
        path = os.path.abspath(path)
        self.file_title.configure(text=os.path.basename(path))
        self.file_sub.configure(text="여는 중…")
        self.status.configure(text="PDF 를 여는 중이에요…", fg=MUTED)
        self.go_btn.configure_button(enabled=False)

        def work():
            try:
                src = S.PdfSource(path)
                self.q.put(("loaded", src))
            except Exception as e:
                self.q.put(("load_error", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, src: S.PdfSource):
        if self.src is not None:
            self.src.close()
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
        self.src = src
        info = src.info
        self.file_title.configure(text=os.path.basename(info.path))
        self.file_sub.configure(text=f"{info.pages:,}쪽  ·  {S.human_size(info.size)}  ·  "
                                     f"한 쪽 평균 {S.human_size(info.size / max(1, info.pages))}")
        self._draw_doc_icon(True)
        self.pick_btn.configure_button(text="다른 파일")
        stem = os.path.splitext(os.path.basename(info.path))[0]
        if not self.out_custom:
            self.out_dir = os.path.join(os.path.dirname(info.path), f"{stem}_분할")
        self._show_out()
        self.page_total_lbl.configure(text=f"/ {info.pages:,}")
        if pdfium is not None and ImageTk is not None:
            try:
                self.doc = pdfium.PdfDocument(info.path)
            except Exception:
                self.doc = None
        self.preview_page = 1
        self.goto(1)
        self.status.configure(text="나누는 방식을 고르고 ‘분할 시작’을 누르세요", fg=MUTED)
        self.bar.set(0, ACCENT)
        self.update_plan()

    # ---------------------------------------------------------- 미리보기
    def _thumb_placeholder(self, msg="미리보기"):
        c = self.thumb_cv
        c.delete("all")
        c.create_text(self.thumb_w / 2, self.thumb_h / 2, text=msg, fill="#B7BACB",
                      font=f(10), justify="center")

    def _goto_entry(self):
        try:
            self.goto(int(self.page_var.get().replace(",", "").strip()))
        except ValueError:
            self.page_var.set(str(self.preview_page))

    def _wheel(self, e):
        self.goto(self.preview_page + (-1 if e.delta > 0 else 1))

    def goto(self, n):
        if self.src is None:
            return
        n = max(1, min(self.src.pages, n))
        self.preview_page = n
        self.page_var.set(str(n))
        if self.doc is None:
            self._thumb_placeholder(f"{n}쪽\n\n(미리보기를 쓰려면\n1_install.bat 를 다시 실행)")
            return
        try:
            page = self.doc[n - 1]
            pw, ph = page.get_size()
            scale = min((self.thumb_w - 12) / pw, (self.thumb_h - 12) / ph)
            img = page.render(scale=scale).to_pil()
            page.close()
            self.thumb = ImageTk.PhotoImage(img)
            c = self.thumb_cv
            c.delete("all")
            c.create_image(self.thumb_w / 2, self.thumb_h / 2, image=self.thumb)
            c.create_text(self.thumb_w - 8, self.thumb_h - 8, text=f"{n}", anchor="se",
                          fill=ACCENT_D, font=f(9, "bold"))
        except Exception:
            self._thumb_placeholder(f"{n}쪽\n(이 쪽은 미리보기를 못 그렸어요)")

    def cut_here(self):
        if self.src is None:
            return
        n = self.preview_page
        if n >= self.src.pages:
            self.status.configure(text="마지막 쪽 뒤에서는 자를 수 없어요", fg=WARN)
            return
        cur = self.spec_var.get().strip()
        if "-" in cur:
            cur = ""
        nums = [x.strip() for x in cur.replace(" ", ",").split(",") if x.strip().isdigit()]
        if str(n) not in nums:
            nums.append(str(n))
        nums = sorted(set(nums), key=int)
        if self.mode != 0:
            self.seg.select(0)
        self.spec_var.set(", ".join(nums))
        self.status.configure(text=f"{n}쪽 뒤에 자르는 곳을 넣었어요 ✂", fg=ACCENT_D)

    def _on_row(self, _e):
        sel = self.tree.selection()
        if not sel or self.src is None:
            return
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.ranges):
            self.goto(self.ranges[idx][0])

    # ---------------------------------------------------------- 계획
    def compute_ranges(self):
        src = self.src
        if src is None:
            return []
        total = src.pages
        if self.mode == 0:
            return S.parse_page_spec(self.spec_var.get(), total)
        if self.mode == 1:
            if self.sub_mode.get() == 0:
                return S.ranges_every(self._int(self.every_var.get(), "쪽 수"), total)
            return S.ranges_into(self._int(self.count_var.get(), "조각 개수"), total)
        return S.estimate_ranges_by_size(self._limit_bytes(), total, src.size)

    @staticmethod
    def _int(s, what):
        s = s.replace(",", "").strip()
        if not s.isdigit():
            raise S.SplitError(f"{what}에 숫자를 넣어 주세요.")
        return int(s)

    def _limit_bytes(self):
        s = self.mb_var.get().replace(",", "").strip()
        try:
            mb = float(s)
        except ValueError:
            raise S.SplitError("MB 칸에 숫자를 넣어 주세요.")
        if mb < 0.1:
            raise S.SplitError("0.1 MB 이상으로 넣어 주세요.")
        return int(mb * 1024 * 1024)

    def update_plan(self):
        if self.running or not hasattr(self, "tree"):
            return
        self.tree.delete(*self.tree.get_children())
        self.ranges = []
        if self.src is None:
            self.summary.configure(text="")
            self.tree_note.configure(text="")
            return
        try:
            self.ranges = self.compute_ranges()
            self.plan_error = ""
        except S.SplitError as e:
            self.plan_error = str(e)
        if self.plan_error:
            self.summary.configure(text="")
            self.tree_note.configure(text=self.plan_error, fg=WARN)
            self.go_btn.configure_button(enabled=False)
            return
        per = self.src.size / max(1, self.src.pages)
        limit = None
        if self.mode == 2:
            try:
                limit = self._limit_bytes()
            except S.SplitError:
                pass
        for i, (a, b) in enumerate(self.ranges, 1):
            n = b - a + 1
            est = per * n
            tags = ["odd"] if i % 2 == 0 else []
            pages = f"{a:,}쪽" if a == b else f"{a:,} ~ {b:,}쪽"
            self.tree.insert("", "end", values=(i, pages, f"{n:,}", "약 " + S.human_size(est)),
                             tags=tags)
        cnt = len(self.ranges)
        prefix = "약 " if self.mode == 2 else ""
        self.summary.configure(text=f"{prefix}{cnt}개 조각으로 나뉘어요")
        note = "용량은 쪽 수로 어림한 값이라 실제와 조금 달라요. 다 만들면 진짜 용량으로 바뀌어요."
        if self.mode == 2 and limit:
            note = f"조각마다 {S.human_size(limit)} 이하가 되도록 만들면서 맞춰요. 실제 개수는 달라질 수 있어요."
        self.tree_note.configure(text=note, fg=MUTED)
        self.go_btn.configure_button(enabled=True)

    # ---------------------------------------------------------- 실행
    def start(self):
        if self.running:
            self.cancel_flag = True
            self.status.configure(text="취소하는 중… (지금 만드는 조각까지만)", fg=WARN)
            return
        if self.src is None:
            return
        try:
            ranges = self.compute_ranges()
            limit = self._limit_bytes() if self.mode == 2 else None
        except S.SplitError as e:
            messagebox.showwarning(APP_NAME, str(e))
            return
        out_dir = self.out_dir
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"저장 폴더를 만들 수 없어요.\n{e}")
            return
        existing = [x for x in os.listdir(out_dir) if x.lower().endswith(".pdf")]
        if existing:
            n = 2
            while os.path.exists(f"{out_dir} ({n})"):
                n += 1
            fresh = f"{out_dir} ({n})"
            ans = messagebox.askyesnocancel(
                APP_NAME, f"저장 폴더에 이미 PDF 가 {len(existing)}개 있어요.\n\n"
                          f"[예]  새 폴더에 저장 → {os.path.basename(fresh)}\n"
                          "[아니요]  같은 폴더에 저장 (이름 같으면 덮어씀)")
            if ans is None:
                return
            if ans:
                out_dir = fresh
                os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self.src.path))[0]
        self.running = True
        self.cancel_flag = False
        self.go_btn.configure_button(text="취소", kind="danger")
        self.open_btn.configure_button(enabled=False)
        self.pick_btn.configure_button(enabled=False)
        self.bar.set(0, ACCENT)
        src = self.src

        def prog(frac, msg):
            self.q.put(("progress", frac, msg))

        def work():
            try:
                if limit is not None:
                    res = S.split_by_size(src, limit, out_dir, stem, prog, lambda: self.cancel_flag)
                else:
                    res = S.split_ranges(src, ranges, out_dir, stem, prog, lambda: self.cancel_flag)
                self.q.put(("done", res, out_dir, limit))
            except S.Cancelled:
                self.q.put(("cancelled", out_dir))
            except Exception as e:
                self.q.put(("error", f"{e}\n\n{traceback.format_exc(limit=3)}"))
        threading.Thread(target=work, daemon=True).start()

    def _finish_ui(self):
        self.running = False
        self.go_btn.configure_button(text="분할 시작  ▶", kind="primary", enabled=True)
        self.pick_btn.configure_button(enabled=True)

    def _done(self, res, out_dir, limit):
        self._finish_ui()
        self.last_out = out_dir
        self.open_btn.configure_button(enabled=True)
        self.bar.set(1, OK)
        self.tree.delete(*self.tree.get_children())
        self.ranges = [(a, b) for _, a, b, _ in res]
        over = 0
        for i, (p, a, b, size) in enumerate(res, 1):
            tags = ["done"]
            if limit and size > limit:
                tags = ["big"]
                over += 1
            if i % 2 == 0:
                tags.append("odd")
            pages = f"{a:,}쪽" if a == b else f"{a:,} ~ {b:,}쪽"
            self.tree.insert("", "end", values=(i, pages, f"{b - a + 1:,}", "✓ " + S.human_size(size)),
                             tags=tags)
        biggest = max((r[3] for r in res), default=0)
        self.summary.configure(text=f"{len(res)}개 파일 완성!")
        note = f"가장 큰 조각: {S.human_size(biggest)}"
        if over:
            note += f"  ·  ⚠ 한 쪽만으로 제한을 넘는 조각 {over}개 (더 쪼갤 수 없어요)"
        self.tree_note.configure(text=note, fg=WARN if over else OK)
        self.status.configure(text=f"완료!  {out_dir}", fg=OK)

    def open_folder(self):
        d = self.last_out or self.out_dir
        if not d or not os.path.isdir(d):
            return
        try:
            if sys.platform == "win32":
                os.startfile(d)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", d])
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, frac, text = msg
                    self.bar.set(frac)
                    self.status.configure(text=f"{text}   {frac * 100:.0f}%",
                                          fg=WARN if text.startswith("⚠") else TEXT)
                elif kind == "loaded":
                    self._loaded(msg[1])
                elif kind == "load_error":
                    self.file_sub.configure(text="열지 못했어요")
                    self.status.configure(text="PDF 를 열지 못했어요", fg=WARN)
                    messagebox.showerror(APP_NAME, msg[1])
                elif kind == "done":
                    self._done(*msg[1:])
                elif kind == "cancelled":
                    self._finish_ui()
                    self.last_out = msg[1]
                    self.open_btn.configure_button(enabled=True)
                    self.bar.set(0)
                    self.status.configure(text="취소했어요. 이미 만든 조각은 폴더에 남아 있어요.",
                                          fg=WARN)
                    self.update_plan()
                elif kind == "error":
                    self._finish_ui()
                    self.bar.set(0)
                    self.status.configure(text="문제가 생겼어요", fg=WARN)
                    messagebox.showerror(APP_NAME, "분할하다가 문제가 생겼어요.\n\n" + msg[1])
                    self.update_plan()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
