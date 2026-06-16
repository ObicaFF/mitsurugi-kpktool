import os, struct, json, io
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import kpktool, b04tool, e3tool, fmtool, textool

SUBTITLE_WARN = 16
CATEGORIES = ['all', 'text', 'image', 'font', 'mesh', 'audio', 'other']


def sniff(raw):
    return kpktool._sniff(raw)


def category(raw, t):
    if t in ('b04', 'e3'): return 'text'
    if t in ('tex', 'dds', 'bmp', 'png'): return 'image'
    if raw[:2] == b'FM': return 'font'
    if t == 'b14': return 'mesh'
    if t == 'ogg': return 'audio'
    return 'other'


def strings_of(raw, t):
    try:
        if t == 'b04':
            return b04tool.parse(raw)['strings']
        if t == 'e3':
            m = e3tool.parse(raw)
            return m['strings'] if m['has_block'] else []
    except Exception:
        return []
    return []


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Mitsurugi Studio')
        self.geometry('1360x800')
        self.kpk_path = self.exe_path = None
        self.unpacked = None
        self.files = []
        self.by_key = {}
        self.edits = {}
        self.bin_edits = {}
        self.ref_by_key = {}
        self.ref_name = ''
        self.preview_img = None
        self.sort_col = None
        self.sort_rev = False
        self._build_ui()

    def _build_ui(self):
        bar = ttk.Frame(self); bar.pack(fill='x', padx=6, pady=4)
        for txt, cmd in [('Open kpk+exe', self.open_archive),
                         ('Load reference', self.load_reference),
                         ('Build patch', self.build_patch), ('Diff with...', self.diff_with),
                         ('Extract file', self.extract_file), ('Extract all...', self.extract_all),
                         ('Export PNG', self.export_png), ('Import PNG', self.import_texture),
                         ('Export text JSON', self.export_json), ('Import text JSON', self.import_json)]:
            ttk.Button(bar, text=txt, command=cmd).pack(side='left', padx=2)
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add('write', lambda *a: self.refresh_list())
        ttk.Entry(bar, textvariable=self.filter_var, width=14).pack(side='right')
        ttk.Label(bar, text='filter:').pack(side='right')
        self.cat_var = tk.StringVar(value='all')
        self.cat_cb = ttk.Combobox(bar, textvariable=self.cat_var, values=CATEGORIES, width=10, state='readonly')
        self.cat_cb.pack(side='right', padx=4)
        self.cat_cb.bind('<<ComboboxSelected>>', lambda *a: self.refresh_list())
        ttk.Label(bar, text='type:').pack(side='right')

        info = ttk.Frame(self); info.pack(fill='x', padx=6)
        self.search_var = tk.StringVar()
        ttk.Label(info, text='search text:').pack(side='left')
        e = ttk.Entry(info, textvariable=self.search_var, width=36); e.pack(side='left', padx=4)
        e.bind('<Return>', lambda *a: self.search_text())
        ttk.Button(info, text='Find in all text', command=self.search_text).pack(side='left')
        self.summary = tk.StringVar(value='')
        ttk.Label(info, textvariable=self.summary).pack(side='right')

        body = ttk.Panedwindow(self, orient='horizontal'); body.pack(fill='both', expand=True, padx=6, pady=4)
        left = ttk.Frame(body); body.add(left, weight=1)
        cols = ('idx', 'key', 'cat', 'type', 'size', 'ed')
        self.tree = ttk.Treeview(left, columns=cols, show='headings', height=32)
        for c, w in zip(cols, (46, 84, 50, 48, 70, 26)):
            self.tree.heading(c, text=c, command=lambda cc=c: self.sort_by(cc))
            self.tree.column(c, width=w, anchor='w')
        self.tree.tag_configure('edited', background='#fff2c2')
        self.tree.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(left, command=self.tree.yview); sb.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=sb.set)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)

        right = ttk.Frame(body); body.add(right, weight=3)
        self.fileinfo = tk.StringVar(value='')
        ttk.Label(right, textvariable=self.fileinfo, relief='groove', anchor='w').pack(fill='x')
        self.nb = ttk.Notebook(right); self.nb.pack(fill='both', expand=True)

        self.tab_text = ttk.Frame(self.nb); self.nb.add(self.tab_text, text='Text')
        self.lb = tk.Listbox(self.tab_text, height=12); self.lb.pack(fill='both', expand=True)
        self.lb.bind('<<ListboxSelect>>', self.on_str_select)
        grid = ttk.Frame(self.tab_text); grid.pack(fill='x')
        ttk.Label(grid, text='Reference (JP/EN):').grid(row=0, column=0, sticky='w')
        self.ref_field = tk.Text(grid, height=2, background='#eef'); self.ref_field.grid(row=1, column=0, sticky='ew')
        ttk.Label(grid, text='Original:').grid(row=2, column=0, sticky='w')
        self.orig_field = tk.Text(grid, height=2, background='#eee'); self.orig_field.grid(row=3, column=0, sticky='ew')
        ttk.Label(grid, text='Translation (edit):').grid(row=4, column=0, sticky='w')
        self.str_entry = tk.Text(grid, height=3); self.str_entry.grid(row=5, column=0, sticky='ew')
        self.str_entry.bind('<KeyRelease>', lambda *a: self.update_charinfo())
        grid.columnconfigure(0, weight=1)
        btns = ttk.Frame(grid); btns.grid(row=5, column=1, sticky='ns')
        self.charinfo = tk.StringVar(value='')
        ttk.Label(btns, textvariable=self.charinfo, foreground='#444').pack()
        ttk.Button(btns, text='Apply', command=self.apply_line).pack(fill='x')
        ttk.Button(btns, text='← copy Original', command=self.copy_original).pack(fill='x')

        self.tab_img = ttk.Frame(self.nb); self.nb.add(self.tab_img, text='Texture')
        self.canvas = tk.Label(self.tab_img, background='#2a2a32'); self.canvas.pack(fill='both', expand=True)

        self.tab_font = ttk.Frame(self.nb); self.nb.add(self.tab_font, text='Font')
        self.font_info = scrolledtext.ScrolledText(self.tab_font, font=('Consolas', 9)); self.font_info.pack(fill='both', expand=True)

        self.tab_hex = ttk.Frame(self.nb); self.nb.add(self.tab_hex, text='Hex/Info')
        self.hex = scrolledtext.ScrolledText(self.tab_hex, font=('Consolas', 9)); self.hex.pack(fill='both', expand=True)

        self.status = tk.StringVar(value='open a kpk + exe to start')
        ttk.Label(self, textvariable=self.status, relief='sunken', anchor='w').pack(fill='x')

    def open_archive(self):
        kpk = filedialog.askopenfilename(title='data0.kpk', filetypes=[('kpk', '*.kpk'), ('all', '*.*')])
        if not kpk: return
        exe = filedialog.askopenfilename(title='mitsurugi.exe', filetypes=[('exe', '*.exe'), ('all', '*.*')])
        if not exe: return
        self.status.set('unpacking...'); self.update()
        self.kpk_path, self.exe_path = kpk, exe
        self.unpacked = kpktool.unpack_exact(kpk, exe)
        self.files = self.unpacked['files']
        self.by_key = {f['key']: f for f in self.files}
        self.edits = {}
        self.bin_edits = {}
        from collections import Counter
        c = Counter(); types = set(); lines = 0
        for f in self.files:
            raw = bytes(f['raw_bytes']); t = sniff(raw); c[category(raw, t)] += 1; types.add(t)
            if t in ('b04', 'e3'): lines += len(strings_of(raw, t))
        self.cat_cb['values'] = CATEGORIES + ['--'] + sorted(types)
        self.summary.set('%d files | %d text lines | %s' %
                         (len(self.files), lines, ' '.join('%s:%d' % (k, v) for k, v in c.most_common())))
        self.refresh_list()
        self.status.set('loaded %s' % os.path.basename(kpk))

    def load_reference(self):
        kpk = filedialog.askopenfilename(title='reference data0.kpk (JP/EN)')
        if not kpk: return
        exe = filedialog.askopenfilename(title='reference mitsurugi.exe')
        if not exe: return
        u = kpktool.unpack_exact(kpk, exe)
        self.ref_by_key = {f['key']: bytes(f['raw_bytes']) for f in u['files']}
        self.ref_name = os.path.basename(kpk)
        self.status.set('reference loaded: %s (%d files)' % (self.ref_name, len(self.ref_by_key)))

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        flt = self.filter_var.get().lower()
        cat = self.cat_var.get()
        for i, f in enumerate(self.files):
            raw = bytes(f['raw_bytes']); t = sniff(raw); cc = category(raw, t)
            if cat not in ('all', '--'):
                if cat in CATEGORIES:
                    if cc != cat: continue
                elif t != cat:
                    continue
            ed = '*' if (f['key'] in self.edits or f['key'] in self.bin_edits) else ''
            row = ('%05d' % i, '%08x' % f['key'], cc, t, str(len(f['raw_bytes'])), ed)
            if flt and flt not in ' '.join(row).lower():
                continue
            self.tree.insert('', 'end', iid=str(i), values=row, tags=('edited',) if ed else ())

    def sort_by(self, col):
        items = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        self.sort_rev = (not self.sort_rev) if self.sort_col == col else False
        self.sort_col = col
        def keyf(v):
            try: return (0, int(v[0]))
            except Exception: return (1, v[0].lower())
        items.sort(key=keyf, reverse=self.sort_rev)
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, '', idx)
        for c in ('idx', 'key', 'cat', 'type', 'size', 'ed'):
            arrow = (' ▼' if self.sort_rev else ' ▲') if c == col else ''
            self.tree.heading(c, text=c + arrow)

    def _cur(self):
        sel = self.tree.selection()
        return self.files[int(sel[0])] if sel else None

    def _cur_strings(self, f, t):
        return list(self.edits.get(f['key']) or strings_of(bytes(f['raw_bytes']), t))

    def on_select(self, _):
        f = self._cur()
        if f is None: return
        raw = bytes(f['raw_bytes']); t = sniff(raw)
        extra = ''
        if t == 'tex':
            w = struct.unpack_from('<H', raw, 12)[0]; h = struct.unpack_from('<H', raw, 14)[0]
            extra = '  %dx%d hdr=%d' % (w, h, len(raw) - w * h * 4)
        elif t == 'dds':
            extra = '  %dx%d %s' % (struct.unpack_from('<I', raw, 16)[0],
                                    struct.unpack_from('<I', raw, 12)[0], raw[84:88].decode('latin1', 'replace'))
        elif raw[:2] == b'FM':
            extra = '  font'
        self.fileinfo.set('key %08x | idx %d | off 0x%x | %s | %d bytes | %s | %s%s' %
                          (f['key'], f['entry_idx'], f['off'], 'zlib' if f['comp'] else 'raw',
                           len(raw), category(raw, t), t, extra))
        self.lb.delete(0, 'end')
        for fld in (self.ref_field, self.orig_field, self.str_entry):
            fld.delete('1.0', 'end')
        self.charinfo.set(''); self.canvas.config(image=''); self.hex.delete('1.0', 'end'); self.font_info.delete('1.0', 'end')
        if t in ('b04', 'e3'):
            cur = self._cur_strings(f, t)
            edited = self.edits.get(f['key'])
            orig = strings_of(raw, t)
            for i, s in enumerate(cur):
                mark = '* ' if (edited and i < len(orig) and s != orig[i]) else '  '
                self.lb.insert('end', mark + s.replace('\n', ' / '))
            self.nb.select(self.tab_text)
        elif t in ('tex', 'dds', 'png', 'bmp'):
            self.show_image(self.bin_edits.get(f['key'], raw), t)
            self.nb.select(self.tab_img)
        elif raw[:2] == b'FM':
            self.show_font(raw)
            self.nb.select(self.tab_font)
        else:
            self.hex.insert('end', self.hexdump(raw[:2048]))
            self.nb.select(self.tab_hex)

    def show_image(self, raw, t, maxsz=700):
        try:
            from PIL import Image, ImageTk
            img = textool.decode(raw)[0] if t == 'tex' else Image.open(io.BytesIO(raw)).convert('RGBA')
            bg = Image.new('RGBA', img.size, (42, 42, 50, 255))
            comp = Image.alpha_composite(bg, img).convert('RGB'); comp.thumbnail((maxsz, maxsz))
            self.preview_img = ImageTk.PhotoImage(comp)
            self.canvas.config(image=self.preview_img)
        except Exception as e:
            messagebox.showerror('image', str(e))

    def show_font(self, raw):
        m = fmtool.parse(raw)
        self.font_info.insert('end', 'glyphs %d\n\n' % m['glyph_count'])
        names = {0: 'Main_46', 1: 'Main_28 (subtitles)', 2: 'System_28 (menu)'}
        for logical in (0, 1, 2):
            try:
                recs = fmtool.page_records(m, logical)
                dims = m['pages'][fmtool._base_for_logical(m, logical)]['dims']
                self.font_info.insert('end', 'page %d %s: %d glyphs, atlas %s\n   cps: %s\n\n' %
                                      (logical, names.get(logical, ''), len(recs), dims,
                                       ' '.join('%04x' % r[0] for r in recs)))
            except Exception:
                pass

    def on_str_select(self, _):
        f = self._cur(); sel = self.lb.curselection()
        if f is None or not sel: return
        t = sniff(bytes(f['raw_bytes'])); i = sel[0]
        strs = self._cur_strings(f, t)
        orig = strings_of(bytes(f['raw_bytes']), t)
        self.orig_field.delete('1.0', 'end'); self.orig_field.insert('1.0', orig[i] if i < len(orig) else '')
        self.ref_field.delete('1.0', 'end')
        ref_raw = self.ref_by_key.get(f['key'])
        if ref_raw:
            rs = strings_of(ref_raw, sniff(ref_raw))
            self.ref_field.insert('1.0', rs[i] if i < len(rs) else '(нет в референсе)')
        self.str_entry.delete('1.0', 'end'); self.str_entry.insert('1.0', strs[i])
        self.update_charinfo()

    def copy_original(self):
        o = self.orig_field.get('1.0', 'end-1c')
        self.str_entry.delete('1.0', 'end'); self.str_entry.insert('1.0', o); self.update_charinfo()

    def update_charinfo(self):
        ls = self.str_entry.get('1.0', 'end-1c').split('\n')
        longest = max((len(x) for x in ls), default=0)
        warn = '  CLIP RISK >%d' % SUBTITLE_WARN if longest > SUBTITLE_WARN else ''
        self.charinfo.set('%d lines\nmax %d ch%s' % (len(ls), longest, warn))

    def apply_line(self):
        f = self._cur(); sel = self.lb.curselection()
        if f is None or not sel: return
        t = sniff(bytes(f['raw_bytes']))
        if t not in ('b04', 'e3'): return
        strs = self._cur_strings(f, t)
        strs[sel[0]] = self.str_entry.get('1.0', 'end-1c')
        self.edits[f['key']] = strs
        self.refresh_list()
        for iid in self.tree.get_children(''):
            if int(iid) == self.files.index(f):
                self.tree.selection_set(iid); break
        self.lb.selection_clear(0, 'end'); self.lb.selection_set(sel[0])
        self.status.set('edited %08x line %d (%d files unsaved)' % (f['key'], sel[0], len(self.edits)))

    def build_patch(self):
        if not self.unpacked or (not self.edits and not self.bin_edits):
            messagebox.showinfo('build', 'no edits'); return
        out_kpk = filedialog.asksaveasfilename(defaultextension='.kpk', initialfile='data0.kpk')
        if not out_kpk: return
        out_exe = os.path.join(os.path.dirname(out_kpk), 'mitsurugi.exe')
        repl = {}
        for key, strs in self.edits.items():
            raw = bytes(self.by_key[key]['raw_bytes']); t = sniff(raw)
            tool = b04tool if t == 'b04' else e3tool
            m = tool.parse(raw); tool.set_strings(m, strs); repl[key] = tool.build(m)
        repl.update(self.bin_edits)
        nk, patches = kpktool.repack_multi(self.unpacked, repl)
        ne = kpktool.patch_exe_directory(open(self.exe_path, 'rb').read(), patches)
        open(out_kpk, 'wb').write(nk); open(out_exe, 'wb').write(ne)
        messagebox.showinfo('build', 'wrote:\n%s\n%s\n%d files edited' % (out_kpk, out_exe, len(repl)))

    def export_json(self):
        if not self.files: return
        out = filedialog.asksaveasfilename(defaultextension='.json', initialfile='text.json')
        if not out: return
        flat = {}
        for f in self.files:
            raw = bytes(f['raw_bytes']); t = sniff(raw)
            for i, s in enumerate(self._cur_strings(f, t) if f['key'] in self.edits else strings_of(raw, t)):
                flat['%08x[%d]' % (f['key'], i)] = s
        json.dump(flat, io.open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        self.status.set('exported %d strings -> %s' % (len(flat), out))

    def import_json(self):
        if not self.files: return
        path = filedialog.askopenfilename(filetypes=[('json', '*.json')])
        if not path: return
        data = json.load(io.open(path, encoding='utf-8'))
        per = {}
        for k, v in data.items():
            try:
                key = int(k[:8], 16); idx = int(k[k.index('[') + 1:k.index(']')])
            except Exception:
                continue
            per.setdefault(key, {})[idx] = v
        n = 0
        for key, idxmap in per.items():
            if key not in self.by_key: continue
            raw = bytes(self.by_key[key]['raw_bytes']); t = sniff(raw)
            strs = list(strings_of(raw, t)); changed = False
            for i, v in idxmap.items():
                if 0 <= i < len(strs) and strs[i] != v:
                    strs[i] = v; changed = True; n += 1
            if changed: self.edits[key] = strs
        self.refresh_list()
        self.status.set('imported %d edits from %s' % (n, os.path.basename(path)))

    def search_text(self):
        q = self.search_var.get()
        if not q or not self.files: return
        hits = []
        for f in self.files:
            raw = bytes(f['raw_bytes']); t = sniff(raw)
            for i, s in enumerate(self._cur_strings(f, t) if f['key'] in self.edits else strings_of(raw, t)):
                if q.lower() in s.lower():
                    hits.append('%08x[%d]  %s' % (f['key'], i, s.replace('\n', ' / ')))
        self.hex.delete('1.0', 'end')
        self.hex.insert('end', 'FOUND %d:\n\n%s' % (len(hits), '\n'.join(hits[:800])))
        self.nb.select(self.tab_hex)
        self.status.set('%d matches for %r' % (len(hits), q))

    def import_texture(self):
        f = self._cur()
        if f is None: return
        raw = bytes(f['raw_bytes']); t = sniff(raw)
        if t not in ('tex', 'dds'):
            messagebox.showwarning('import', 'выбери .tex или .dds'); return
        from PIL import Image
        if t == 'tex':
            w = struct.unpack_from('<H', raw, 12)[0]; h = struct.unpack_from('<H', raw, 14)[0]
            fmt_note = 'tex %dx%d' % (w, h)
        else:
            h = struct.unpack_from('<I', raw, 12)[0]; w = struct.unpack_from('<I', raw, 16)[0]
            fourcc = raw[84:88].decode('latin1', 'replace')
            if fourcc not in ('DXT1', 'DXT5'):
                messagebox.showwarning('import', 'DDS-формат %r не поддержан (только DXT1/DXT5)' % fourcc); return
            fmt_note = 'dds %dx%d %s' % (w, h, fourcc)
        png = filedialog.askopenfilename(title='PNG для %08x (%s)' % (f['key'], fmt_note),
                                         filetypes=[('png', '*.png'), ('all', '*.*')])
        if not png: return
        try:
            img = Image.open(png).convert('RGBA')
        except Exception as e:
            messagebox.showerror('import', 'не открылось как изображение:\n%s' % e); return
        if img.size != (w, h):
            if not messagebox.askyesno('проверка',
                    'Размеры НЕ совпадают!\nPNG: %dx%d\nатлас: %dx%d\n\n'
                    'Возможно подсунул не тот файл.\nВсё равно вставить (с ресайзом до %dx%d)?'
                    % (img.width, img.height, w, h, w, h)):
                self.status.set('импорт отменён (размер не совпал)'); return
            img = img.resize((w, h))
        if t == 'tex':
            hdr = len(raw) - w * h * 4
            r, g, b, a = img.split()
            new = raw[:hdr] + bytes(Image.merge('RGBA', (b, g, r, a)).tobytes())
            if len(new) != len(raw):
                messagebox.showerror('import', 'размер не сошёлся (%d != %d)' % (len(new), len(raw))); return
        else:
            buf = io.BytesIO(); img.save(buf, format='DDS', pixel_format=fourcc); new = buf.getvalue()
        self.bin_edits[f['key']] = new
        self.refresh_list()
        self.show_image(new, t); self.nb.select(self.tab_img)
        self.status.set('импортирован PNG в %08x (%s, ок)' % (f['key'], fmt_note))

    def extract_file(self):
        f = self._cur()
        if f is None: return
        raw = bytes(f['raw_bytes']); t = sniff(raw)
        out = filedialog.asksaveasfilename(initialfile='%08x.%s' % (f['key'], t),
                                           defaultextension='.' + t)
        if not out: return
        open(out, 'wb').write(raw)
        self.status.set('extracted %08x (%d bytes) -> %s' % (f['key'], len(raw), out))

    def extract_all(self):
        if not self.files: return
        d = filedialog.askdirectory(title='extract all files into...')
        if not d: return
        cat = self.cat_var.get()
        n = 0
        manifest = []
        for i, f in enumerate(self.files):
            raw = bytes(f['raw_bytes']); t = sniff(raw)
            if cat not in ('all', '--'):
                if cat in CATEGORIES:
                    if category(raw, t) != cat: continue
                elif t != cat:
                    continue
            name = '%05d_%08x.%s' % (i, f['key'], t)
            open(os.path.join(d, name), 'wb').write(raw)
            manifest.append(dict(i=i, key='%08x' % f['key'], type=t,
                                 cat=category(raw, t), size=len(raw), name=name))
            n += 1
        json.dump(manifest, io.open(os.path.join(d, 'manifest.json'), 'w', encoding='utf-8'), indent=1)
        self.status.set('extracted %d files (%s) -> %s' % (n, cat, d))
        messagebox.showinfo('extract all', 'extracted %d files into\n%s' % (n, d))

    def export_png(self):
        f = self._cur()
        if f is None: return
        raw = bytes(self.bin_edits.get(f['key'], f['raw_bytes'])); t = sniff(raw)
        if t not in ('tex', 'dds', 'png', 'bmp'): return
        out = filedialog.asksaveasfilename(defaultextension='.png')
        if not out: return
        from PIL import Image
        img = textool.decode(raw)[0] if t == 'tex' else Image.open(io.BytesIO(raw)).convert('RGBA')
        img.save(out)
        self.status.set('saved ' + out)

    def diff_with(self):
        if not self.unpacked: return
        kpk2 = filedialog.askopenfilename(title='other data0.kpk')
        if not kpk2: return
        exe2 = filedialog.askopenfilename(title='other mitsurugi.exe')
        if not exe2: return
        u2 = kpktool.unpack_exact(kpk2, exe2)
        a = {f['key']: bytes(f['raw_bytes']) for f in self.files}
        b = {f['key']: bytes(f['raw_bytes']) for f in u2['files']}
        lines = []
        for k in sorted(set(a) | set(b)):
            if k not in a: lines.append('+ %08x only in other' % k)
            elif k not in b: lines.append('- %08x only in current' % k)
            elif a[k] != b[k]: lines.append('~ %08x differs (%d vs %d)' % (k, len(a[k]), len(b[k])))
        self.hex.delete('1.0', 'end')
        self.hex.insert('end', 'DIFF %d changed\n\n%s' % (len(lines), '\n'.join(lines)))
        self.nb.select(self.tab_hex)

    @staticmethod
    def hexdump(b):
        out = []
        for i in range(0, len(b), 16):
            chunk = b[i:i + 16]
            out.append('%08x  %-48s  %s' % (i, ' '.join('%02x' % c for c in chunk),
                       ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)))
        return '\n'.join(out)


if __name__ == '__main__':
    App().mainloop()
