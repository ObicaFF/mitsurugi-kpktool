import struct, sys


def info(data):
    w = struct.unpack_from('<H', data, 12)[0]
    h = struct.unpack_from('<H', data, 14)[0]
    hdr = len(data) - w * h * 4
    return w, h, hdr


def decode(data):
    w, h, hdr = info(data)
    px = data[hdr:hdr + w * h * 4]
    from PIL import Image
    img = Image.frombytes('RGBA', (w, h), bytes(px))
    b, g, r, a = img.split()
    return Image.merge('RGBA', (r, g, b, a)), (w, h, hdr)


def to_png(tex_path, png_path):
    data = open(tex_path, 'rb').read()
    img, (w, h, hdr) = decode(data)
    img.save(png_path)
    sys.stderr.write('%dx%d hdr=%d -> %s\n' % (w, h, hdr, png_path))


def encode(orig_tex, png_path, out_tex):
    from PIL import Image
    data = open(orig_tex, 'rb').read()
    w, h, hdr = info(data)
    img = Image.open(png_path).convert('RGBA').resize((w, h))
    r, g, b, a = img.split()
    bgra = Image.merge('RGBA', (b, g, r, a)).tobytes()
    open(out_tex, 'wb').write(data[:hdr] + bgra)
    sys.stderr.write('wrote %s (%dx%d hdr=%d)\n' % (out_tex, w, h, hdr))


def dds_to_png(dds_path, png_path):
    from PIL import Image
    Image.open(dds_path).convert('RGBA').save(png_path)
    sys.stderr.write('-> %s\n' % png_path)


def png_to_dds(orig_dds, png_path, out_dds):
    from PIL import Image
    data = open(orig_dds, 'rb').read()
    h = struct.unpack_from('<I', data, 12)[0]
    w = struct.unpack_from('<I', data, 16)[0]
    fourcc = data[84:88].decode('latin1', 'replace')
    if fourcc not in ('DXT1', 'DXT5'):
        raise SystemExit('unsupported DDS format: %r' % fourcc)
    img = Image.open(png_path).convert('RGBA').resize((w, h))
    img.save(out_dds, format='DDS', pixel_format=fourcc)
    sys.stderr.write('wrote %s (%dx%d %s)\n' % (out_dds, w, h, fourcc))


if __name__ == '__main__':
    a = sys.argv
    if len(a) < 2:
        print('usage: textool.py tex2png in.tex out.png | png2tex orig.tex in.png out.tex | '
              'dds2png in.dds out.png | png2dds orig.dds in.png out.dds')
        sys.exit(1)
    if a[1] == 'tex2png':
        to_png(a[2], a[3])
    elif a[1] == 'png2tex':
        encode(a[2], a[3], a[4])
    elif a[1] == 'dds2png':
        dds_to_png(a[2], a[3])
    elif a[1] == 'png2dds':
        png_to_dds(a[2], a[3], a[4])
    else:
        print('unknown command', a[1]); sys.exit(1)
