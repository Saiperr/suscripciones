"""Genera los iconos de la PWA sin dependencias (PNG escrito a mano)."""
import math, struct, zlib, sys, os

A, B = (124, 92, 255), (34, 211, 238)     # violeta -> cian (misma paleta que la app)


def shade(x, y, size, maskable, ss=3):
    """Devuelve (r,g,b,a) 0-255 del píxel (x,y) con supersampling ss×ss."""
    acc = [0.0, 0.0, 0.0, 0.0]
    for i in range(ss):
        for j in range(ss):
            u, v = (x + (i + .5) / ss) / size, (y + (j + .5) / ss) / size
            # fondo: cuadrado redondeado (o a sangre si es maskable)
            inside = True
            if not maskable:
                r = 0.22
                cx, cy = min(max(u, r), 1 - r), min(max(v, r), 1 - r)
                inside = (u - cx) ** 2 + (v - cy) ** 2 <= r * r
            if not inside:
                continue
            t = (u + v) / 2
            col = [A[k] + (B[k] - A[k]) * t for k in range(3)]
            s = 0.78 if maskable else 1.0                      # zona segura para maskable
            du, dv = (u - .5) / s, (v - .5) / s
            d = math.hypot(du, dv)
            ang = math.degrees(math.atan2(-dv, du)) % 360       # 0° = derecha, antihorario
            ring = 0.255 <= d <= 0.335 and not (20 <= ang <= 85)
            dot = d <= 0.075
            # punta de flecha en el extremo del hueco
            ax, ay = math.cos(math.radians(85)) * .295, -math.sin(math.radians(85)) * .295
            px, py = du - ax, dv - ay
            head = abs(px) + abs(py) <= 0.085 and px >= -0.02 - abs(py)
            if ring or dot or head:
                col = [255, 255, 255]
            for k in range(3):
                acc[k] += col[k]
            acc[3] += 255
    n = ss * ss
    a = acc[3] / n
    if a == 0:
        return (0, 0, 0, 0)
    return tuple(int(round(acc[k] / (acc[3] / 255))) for k in range(3)) + (int(round(a)),)


def png(path, size, maskable=False):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw += bytes(shade(x, y, size, maskable))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + \
           chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(data)


out = sys.argv[1]
for name, size, m in (("icon-192.png", 192, False), ("icon-512.png", 512, False),
                      ("icon-maskable-512.png", 512, True), ("apple-touch-icon.png", 180, True)):
    png(os.path.join(out, name), size, m)
    print("ok", name)
