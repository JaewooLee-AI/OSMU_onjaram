"""pptx 후처리: 테마의 동아시아(ea)·한글 글꼴을 채우고 글자 언어를 ko-KR로. 사용: python fix_fonts.py deck.pptx FONT"""
import re, shutil, sys, zipfile
src, font = sys.argv[1], sys.argv[2]
tmp = src + ".tmp"
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename.endswith("/"):
            continue
        data = zin.read(item.filename)
        name = item.filename
        if name.startswith("ppt/theme/") and name.endswith(".xml"):
            s = data.decode("utf-8")
            s = s.replace('<a:ea typeface=""/>', f'<a:ea typeface="{font}"/>')
            s = re.sub(r'<a:font script="Hang" typeface="[^"]*"/>', f'<a:font script="Hang" typeface="{font}"/>', s)
            data = s.encode("utf-8")
        elif (name.startswith("ppt/slides/slide") or name.startswith("ppt/slideLayouts/") or name.startswith("ppt/slideMasters/")) and name.endswith(".xml"):
            s = data.decode("utf-8")
            s = s.replace('lang="en-US"', 'lang="ko-KR" altLang="en-US"')
            data = s.encode("utf-8")
        zout.writestr(item, data)
shutil.move(tmp, src)
print("fixed", src)
