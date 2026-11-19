"""Write the deck's theme colours and fonts into a .pptx (pptxgenjs cannot).

    python docs/presentation/apply_theme.py docs/presentation/group4_deck.pptx docs/presentation/theme.json

Replaces <a:clrScheme> and the latin faces of <a:fontScheme> in every ppt/theme/theme*.xml,
so scheme colours used on the slides (text1, accent1, ...) resolve to the group palette.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from xml.sax.saxutils import escape

ORDER = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
         "hlink", "folHlink"]


def patch(xml, theme):
    scheme = (f'<a:clrScheme name="{escape(theme["name"], {chr(34): "&quot;"})}">'
              + "".join(f'<a:{k}><a:srgbClr val="{theme["colors"][k]}"/></a:{k}>' for k in ORDER)
              + "</a:clrScheme>")
    xml = re.sub(r"<a:clrScheme\b.*?</a:clrScheme>", scheme, xml, count=1, flags=re.S)
    for tag, face in (("majorFont", theme["headFontFace"]), ("minorFont", theme["bodyFontFace"])):
        xml = re.sub(rf"(<a:{tag}>\s*<a:latin typeface=\")[^\"]*", rf"\g<1>{face}", xml, count=1)
    return xml


def main(pptx, theme_file):
    with open(theme_file, encoding="utf-8") as fh:
        theme = json.load(fh)
    fd, tmp = tempfile.mkstemp(suffix=".pptx")
    os.close(fd)
    with zipfile.ZipFile(pptx) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if item.is_dir():          # folder entries break some cloud viewers
                continue
            data = zin.read(item.filename)
            if re.fullmatch(r"ppt/theme/theme\d+\.xml", item.filename):
                data = patch(data.decode("utf-8"), theme).encode("utf-8")
            zout.writestr(item, data)
    shutil.move(tmp, pptx)
    print(f"theme '{theme['name']}' applied to {pptx}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
