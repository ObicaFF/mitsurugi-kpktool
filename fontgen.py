import sys
import fmtool


def _render(font, ch, ink_thresh=80):
    from PIL import Image, ImageDraw
    pad = 8
    box = font.size * 3
    img = Image.new('L', (box, box), 0)
    ImageDraw.Draw(img).text((pad, pad), ch, fill=255, font=font)
    bbox = img.getbbox()
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return img.crop((x0, y0, x1, y1))


def _load_tex(path):
    data = open(path, 'rb').read()
    w = int.from_bytes(data[12:14], 'little')
    h = int.from_bytes(data[14:16], 'little')
    hdr = len(data) - w * h * 4
    return bytearray(data[:hdr]), bytearray(data[hdr:]), w, h, hdr


def add_glyphs(fm_path, tex_path, ttf_path, page, codepoints,
               out_fm, out_tex, fmt='magenta', flip=False,
               ttf_size=None, start_v=None, baseline_pad=2, gap=1):
    from PIL import ImageFont
    fm = fmtool.parse(open(fm_path, 'rb').read())
    pd = fmtool.PD[page]
    pinfo = fm['pages'][pd]
    cell_h = max((r[4] for r in fmtool.page_records(fm, page)), default=28)
    if ttf_size is None:
        ttf_size = cell_h
    font = ImageFont.truetype(ttf_path, ttf_size)

    hdr, px, W, H, hsz = _load_tex(tex_path)
    if start_v is None:
        used = [r[2] + r[4] for r in fmtool.page_records(fm, page)]
        start_v = (max(used) if used else 0) + 2

    def put_px(x, y, bgra):
        ay = (H - 1 - y) if flip else y
        if 0 <= x < W and 0 <= ay < H:
            o = (ay * W + x) * 4
            px[o:o + 4] = bytes(bgra)

    cur_x, cur_v = 0, start_v
    new_recs = list(fmtool.page_records(fm, page))
    for cp in codepoints:
        glyph = _render(font, chr(cp))
        if glyph is None:
            w = max(6, cell_h // 3)
            new_recs.append((cp, 0, cur_v, w, cell_h))
            continue
        gw, gh = glyph.size
        if cur_x + gw + gap > W:
            cur_x = 0
            cur_v += cell_h + 1
        if cur_v + cell_h > H:
            raise SystemExit('atlas full at v=%d (enlarge or trim)' % cur_v)
        gp = glyph.load()
        top = cell_h - baseline_pad - gh
        for yy in range(gh):
            for xx in range(gw):
                a = gp[xx, yy]
                X = cur_x + xx
                Y = cur_v + top + yy
                if fmt == 'magenta':
                    put_px(X, Y, (255, 255, 255, 255) if a > 80 else (255, 0, 255, 255))
                else:
                    put_px(X, Y, (255, 255, 255, a))
        new_recs.append((cp, cur_x, cur_v, gw + gap, cell_h))
        cur_x += gw + gap

    pages = [fmtool.page_records(fm, 0), fmtool.page_records(fm, 1), fmtool.page_records(fm, 2)]
    pages[page] = new_recs
    fmtool.set_pages(fm, pages[0], pages[1], pages[2])
    open(out_fm, 'wb').write(fmtool.build(fm))
    open(out_tex, 'wb').write(bytes(hdr) + bytes(px))
    sys.stderr.write('added %d glyphs to page %d -> %s + %s (total glyphs %d)\n'
                     % (len(codepoints), page, out_fm, out_tex, len(fm['records'])))


CYRILLIC = list(range(0x410, 0x450)) + [0x401, 0x451]


if __name__ == '__main__':
    a = sys.argv
    if len(a) < 8:
        print('usage: fontgen.py all.fm atlas.tex font.ttf <page 0|1|2> out.fm out.tex '
              '[magenta|alpha] [flip] [cp1,cp2,... | cyr]')
        print('  page1(Main_28)=magenta; page2(System_28)=alpha flip')
        sys.exit(1)
    fm_path, tex_path, ttf_path, page, out_fm, out_tex = a[1:7]
    rest = a[7:]
    fmt = 'magenta'
    flip = False
    cps = CYRILLIC
    for tok in rest:
        if tok in ('magenta', 'alpha'):
            fmt = tok
        elif tok == 'flip':
            flip = True
        elif tok == 'cyr':
            cps = CYRILLIC
        else:
            cps = [int(x, 0) for x in tok.split(',')]
    add_glyphs(fm_path, tex_path, ttf_path, int(page), cps, out_fm, out_tex,
               fmt=fmt, flip=flip)
