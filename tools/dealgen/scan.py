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


def scan_pdf(src, dst, seed, dpi=110, quality=50, profile="normal"):
    rng = random.Random(seed)
    ugly = profile == "ugly"
    if ugly:
        dpi, quality = 96, 38
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
        if ugly:
            # photocopy: crushed greys, low contrast, toner bleed
            arr = np.where(arr < 150, arr * 0.55, 150 + (arr - 150) * 0.6)
            arr = 62 + arr * (150 / 255.0)
        else:
            arr = 22 + arr * (226 / 255.0)
        img = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
        rot = rng.uniform(1.4, 2.4) * rng.choice([-1, 1]) if ugly else rng.uniform(-0.9, 0.9)
        img = img.rotate(rot, resample=Image.BICUBIC, expand=False, fillcolor=60 if ugly else 238)
        img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.9, 1.15) if ugly else rng.uniform(0.55, 0.8)))
        arr = np.asarray(img).astype(np.float32)
        h, w = arr.shape
        # uneven exposure: gentle gradient across the page
        gx = np.linspace(rng.uniform(-10, 0), rng.uniform(0, 8), w)[None, :]
        gy = np.linspace(rng.uniform(-6, 0), rng.uniform(0, 6), h)[:, None]
        arr = arr + gx + gy
        arr = arr + nrng.normal(0, 11.0 if ugly else 7.0, arr.shape)
        if ugly:
            # copier streak and dark top band
            sx = int(w * rng.uniform(0.3, 0.7))
            arr[:, sx:sx + 3] -= 45
            arr[: int(h * 0.012), :] -= 90
        # speckles
        n = int(h * w * (0.0025 if ugly else 0.0006))
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
