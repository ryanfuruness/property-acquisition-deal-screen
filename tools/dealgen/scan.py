"""Turn a text PDF into an image-only 'scanned' PDF: slight rotation, blur, noise, uneven exposure,
scanner edge shadow. No text layer survives."""
from __future__ import annotations

import io
import random

import numpy as np
import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def scan_pdf(src, dst, seed, dpi=110, quality=50):
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    doc = pymupdf.open(str(src))
    c = canvas.Canvas(str(dst), pagesize=A4, invariant=1)
    c.setTitle("scan")
    c.setAuthor("")
    for page in doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        landscape = img.width > img.height
        # paper tint and toner: compress range
        arr = np.asarray(img).astype(np.float32)
        arr = 22 + arr * (226 / 255.0)
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
        img = img.rotate(rng.uniform(-0.9, 0.9), resample=Image.BICUBIC, expand=False, fillcolor=238)
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.55, 0.8)))
        arr = np.asarray(img).astype(np.float32)
        h, w = arr.shape
        # uneven exposure: gentle gradient across the page
        gx = np.linspace(rng.uniform(-10, 0), rng.uniform(0, 8), w)[None, :]
        gy = np.linspace(rng.uniform(-6, 0), rng.uniform(0, 6), h)[:, None]
        arr = arr + gx + gy
        arr = arr + nrng.normal(0, 7.0, arr.shape)
        # speckles
        n = int(h * w * 0.0006)
        ys, xs = nrng.integers(0, h, n), nrng.integers(0, w, n)
        arr[ys, xs] = nrng.uniform(30, 120, n)
        # scanner edge shadow on one side
        sh = int(w * 0.018)
        ramp = np.linspace(70, 0, sh)[None, :]
        if rng.random() < 0.5:
            arr[:, :sh] -= ramp
        else:
            arr[:, -sh:] -= ramp[:, ::-1]
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        buf.seek(0)
        ps = (A4[1], A4[0]) if landscape else A4
        c.setPageSize(ps)
        c.drawImage(ImageReader(buf), 0, 0, width=ps[0], height=ps[1])
        c.showPage()
    c.save()
