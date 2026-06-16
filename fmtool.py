import struct

GLYPH_OFF = 0xc0
PD = {0: 72, 1: 112, 2: 152}
TRAILER = 48


def parse(data):
    glyph_count = struct.unpack_from('<I', data, 28)[0]
    secs = list(struct.unpack_from('<4I', data, 36))
    pages = {}
    for page_field, base in PD.items():
        dims = struct.unpack_from('<HH', data, base + 12)
        start = struct.unpack_from('<I', data, base + 20)[0]
        count = struct.unpack_from('<I', data, base + 24)[0]
        page_no = struct.unpack_from('<I', data, base + 28)[0]
        texhash = struct.unpack_from('<I', data, base + 32)[0]
        pages[base] = dict(dims=dims, start=start, count=count,
                           page=page_no, texhash=texhash)
    records = []
    for i in range(glyph_count):
        cp, u, v, w, h = struct.unpack_from('<HHHBB', data, GLYPH_OFF + i * 8)
        records.append((cp, u, v, w, h))
    strtab = data[secs[2]:secs[3]]
    trailer = data[secs[3]:]
    return dict(header=bytes(data[:GLYPH_OFF]), glyph_count=glyph_count,
                secs=secs, pages=pages, records=records,
                strtab=bytes(strtab), trailer=bytes(trailer))


def build(model):
    fm = bytearray(model['header'])
    records = model['records']
    struct.pack_into('<I', fm, 28, len(records))
    for base, p in model['pages'].items():
        struct.pack_into('<HH', fm, base + 12, p['dims'][0], p['dims'][1])
        struct.pack_into('<I', fm, base + 20, p['start'])
        struct.pack_into('<I', fm, base + 24, p['count'])
    gt = bytearray()
    for cp, u, v, w, h in records:
        gt += struct.pack('<HHHBB', cp, u, v, w, h)
    gt += b'\x00' * 8
    fm += gt
    sec_str = len(fm)
    fm += model['strtab']
    sec_end = len(fm)
    trailer = model['trailer'] if model['trailer'] else b'\x00' * TRAILER
    fm += trailer
    struct.pack_into('<4I', fm, 36, 0x40, GLYPH_OFF, sec_str, sec_end)
    return bytes(fm)


def _base_for_logical(model, logical):
    for base, p in model['pages'].items():
        if p['page'] == logical:
            return base
    raise KeyError('no page with logical number %d' % logical)


def page_records(model, logical):
    p = model['pages'][_base_for_logical(model, logical)]
    return model['records'][p['start']:p['start'] + p['count']]


def set_pages(model, page0, page1, page2):
    by_logical = {0: page0, 1: page1, 2: page2}
    new_records = []
    for logical in (0, 1, 2):
        recs = sorted(by_logical[logical], key=lambda r: r[0])
        base = _base_for_logical(model, logical)
        model['pages'][base]['start'] = len(new_records)
        model['pages'][base]['count'] = len(recs)
        new_records += recs
    model['records'] = new_records


if __name__ == '__main__':
    import sys
    data = open(sys.argv[1], 'rb').read()
    m = parse(data)
    same = build(m) == data
    print('glyphs', m['glyph_count'], 'pages', {k: (v['count'], v['dims']) for k, v in m['pages'].items()})
    print('no-op rebuild identical:', same)
