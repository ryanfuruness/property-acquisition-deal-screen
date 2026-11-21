"""Deterministic xlsx output: fixed document properties and fixed zip timestamps."""
import io
import zipfile
from datetime import datetime

FIXED = datetime(2026, 11, 20, 9, 0, 0)


def finalize_workbook(wb, path, creator="Owner"):
    wb.properties.creator = creator
    wb.properties.lastModifiedBy = creator
    wb.properties.created = FIXED
    wb.properties.modified = FIXED
    buf = io.BytesIO()
    wb.save(buf)
    src = zipfile.ZipFile(io.BytesIO(buf.getvalue()))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                import re
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)", rb"\g<1>2026-11-20T09:00:00Z\g<2>", data)
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 11, 20, 9, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            out.writestr(zi, data)
