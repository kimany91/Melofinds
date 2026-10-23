"""Écrit build/version_info.txt (nom, éditeur, version affichés dans les propriétés
de MelofindsPC.exe) à partir de VERSION dans mf_core.py. Utilisé par la construction."""

import re
import sys
from pathlib import Path

here = Path(__file__).parent
ver = re.search(r'^VERSION = "([\d.]+)"', (here / "mf_core.py").read_text(encoding="utf-8"), re.M).group(1)
t = tuple(int(x) for x in ver.split(".")) + (0,) * (4 - len(ver.split(".")))
out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/version_info.txt")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040C04B0', [
      StringStruct('CompanyName', 'Melofinds'),
      StringStruct('FileDescription', 'Melofinds PC'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', 'MelofindsPC'),
      StringStruct('LegalCopyright', 'Melofinds'),
      StringStruct('OriginalFilename', 'MelofindsPC.exe'),
      StringStruct('ProductName', 'Melofinds PC'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1036, 1200])])
  ]
)
""", encoding="utf-8")
print(ver)
