"""Tiny SVG toolkit for the CassChat architecture diagrams (Group 4, INFT 6000 HW3)."""
from xml.sax.saxutils import escape

FONT = "Arial, 'Liberation Sans', Helvetica, sans-serif"
MONO = "'Courier New', 'Liberation Mono', monospace"
INK, INK2, MUTED = "#1b1b1b", "#4a4a48", "#7a7a75"
C = {
    "cql": "#2a78d6",      # client CQL traffic
    "repl": "#eb6834",     # replication / mutations
    "gossip": "#1b9a6c",   # gossip + internode
    "fault": "#c62f2f",    # fault injection
    "admin": "#6250d6",    # docker exec nodetool / cqlsh
    "file": "#6b6b66",     # file / CSV I/O, logs
}
STYLE = {   # stroke-dasharray per edge kind
    "cql": None, "repl": None, "gossip": "7 5", "fault": "10 4 2 4", "admin": "3 3", "file": "1 4",
}


class SVG:
    def __init__(self, w, h, title=""):
        self.w, self.h = w, h
        self.parts = []
        self.title = title

    def add(self, s):
        self.parts.append(s)

    # ------------------------------------------------------------------ primitives
    def rect(self, x, y, w, h, fill="#fff", stroke=INK2, sw=1.2, rx=8, dash=None, opacity=1.0):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" '
                 f'fill-opacity="{opacity}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=13, weight="normal", color=INK, anchor="start", italic=False, mono=False):
        st = ' font-style="italic"' if italic else ""
        fam = MONO if mono else FONT
        lines = s.split("\n")
        for i, ln in enumerate(lines):
            self.add(f'<text x="{x}" y="{y + i * size * 1.25:.1f}" font-family="{fam}" font-size="{size}" '
                     f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}" xml:space="preserve"{st}>{escape(ln)}</text>')

    def boundary(self, x, y, w, h, label, fill, stroke, dash=None, sw=1.6, size=14, sub=None):
        """Labelled system boundary: tinted area, label in a tab at the top-left."""
        self.rect(x, y, w, h, fill=fill, stroke=stroke, sw=sw, rx=12, dash=dash)
        tw = 9 + len(label) * size * 0.56
        self.add(f'<rect x="{x + 10}" y="{y - 11}" width="{tw:.0f}" height="22" rx="5" fill="{stroke}"/>')
        self.text(x + 15, y + 5, label, size=size - 1, weight="bold", color="#fff")
        if sub:
            self.text(x + 15 + tw, y + 5, sub, size=size - 3, color=INK2, italic=True)

    def box(self, x, y, w, h, title, lines=(), fill="#fff", stroke=INK2, title_color=INK, size=13,
            dash=None, sw=1.3, mono_lines=False, line_size=None):
        self.rect(x, y, w, h, fill=fill, stroke=stroke, sw=sw, rx=7, dash=dash)
        self.text(x + 10, y + 19, title, size=size, weight="bold", color=title_color)
        ls = line_size or size - 2
        for i, ln in enumerate(lines):
            self.text(x + 10, y + 19 + (i + 1) * ls * 1.32, ln, size=ls, color=INK2, mono=mono_lines)

    def defs(self):
        m = []
        for k, col in C.items():
            m.append(f'<marker id="a-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                     f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
        return "<defs>" + "".join(m) + "</defs>"

    def edge(self, pts, kind, label=None, lx=None, ly=None, both=False, sw=2.0, lsize=11.5, lcolor=None,
             anchor="middle", bg=True):
        col = C[kind]
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        dash = STYLE[kind]
        da = f' stroke-dasharray="{dash}"' if dash else ""
        ms = f' marker-start="url(#a-{kind})"' if both else ""
        self.add(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{sw}"{da}{ms} '
                 f'marker-end="url(#a-{kind})" stroke-linejoin="round"/>')
        if label:
            if lx is None:
                (x1, y1), (x2, y2) = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
                lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 6
            if bg:
                lines = label.split("\n")
                wmax = max(len(t) for t in lines) * lsize * 0.53 + 8
                hh = len(lines) * lsize * 1.25 + 4
                bx = lx - wmax / 2 if anchor == "middle" else (lx - 4 if anchor == "start" else lx - wmax + 4)
                self.add(f'<rect x="{bx:.0f}" y="{ly - lsize - 1:.0f}" width="{wmax:.0f}" height="{hh:.0f}" '
                         f'rx="3" fill="#ffffff" fill-opacity="0.92"/>')
            self.text(lx, ly, label, size=lsize, color=lcolor or col, anchor=anchor, weight="bold")

    def legend(self, x, y, items, title="Legend", w=None, cols=1):
        rows = (len(items) + cols - 1) // cols
        w = w or 300
        h = 34 + rows * 22
        self.rect(x, y, w, h, fill="#ffffff", stroke="#c9c9c3", rx=8)
        self.text(x + 12, y + 20, title, size=12.5, weight="bold")
        cw = (w - 20) / cols
        for i, (kind, label) in enumerate(items):
            cx = x + 12 + (i // rows) * cw
            cy = y + 38 + (i % rows) * 22
            if kind.startswith("box:"):
                _, fill, stroke, dash = kind.split(":")
                da = f' stroke-dasharray="{dash}"' if dash else ""
                self.add(f'<rect x="{cx}" y="{cy - 10}" width="34" height="14" rx="3" fill="{fill}" '
                         f'stroke="{stroke}" stroke-width="1.3"{da}/>')
            else:
                dash = STYLE[kind]
                da = f' stroke-dasharray="{dash}"' if dash else ""
                self.add(f'<path d="M{cx},{cy - 3} L{cx + 34},{cy - 3}" stroke="{C[kind]}" stroke-width="2.2"{da} '
                         f'marker-end="url(#a-{kind})"/>')
            self.text(cx + 44, cy + 1, label, size=11.5, color=INK)

    def save(self, path):
        head = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}">')
        title = f"<title>{escape(self.title)}</title>" if self.title else ""
        body = "\n".join(self.parts)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(head + title + self.defs() + f'<rect width="{self.w}" height="{self.h}" fill="#ffffff"/>'
                     + body + "</svg>")
