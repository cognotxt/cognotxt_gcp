import csv
import io
import logging
import os
from pathlib import Path

import cv2
import fitz
import numpy as np
from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai

logger = logging.getLogger("cognotxt.worker")

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")

if not PROJECT_ID:
    import google.auth

    _, PROJECT_ID = google.auth.default()

if not PROJECT_ID:
    raise RuntimeError(
        "Não foi possível determinar GOOGLE_CLOUD_PROJECT"
    )

DOCUMENT_AI_LOCATION = os.getenv("DOCUMENT_AI_LOCATION", "us")
OCR_PROCESSOR_ID = os.environ["GOOGLE_OCR_PROCESSOR_ID"]
FORM_PROCESSOR_ID = os.getenv("GOOGLE_FORM_PROCESSOR_ID", "").strip()

MIN_NATIVE_CHARS = int(os.getenv("SMART_TEXT_MIN_NATIVE_CHARS", "20"))
RENDER_DPI = int(os.getenv("SMART_TEXT_RENDER_DPI", "200"))
TABLE_FORM_PARSER = os.getenv("SMART_TABLE_FORM_PARSER", "true").lower() in {"1", "true", "yes", "sim"}
TABLE_MIN_H = int(os.getenv("SMART_TABLE_MIN_HORIZONTAL_LINES", "3"))
TABLE_MIN_V = int(os.getenv("SMART_TABLE_MIN_VERTICAL_LINES", "2"))
TABLE_LINE_COVERAGE = float(os.getenv("SMART_TABLE_LINE_COVERAGE", "0.35"))
BLANK_DARK_PIXEL_RATIO = float(os.getenv("BLANK_DARK_PIXEL_RATIO", "0.0008"))


def create_document_ai_client():
    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{DOCUMENT_AI_LOCATION}-documentai.googleapis.com")
    )


def process_bytes(content: bytes, mime_type: str, processor_id: str, client):
    name = client.processor_path(PROJECT_ID, DOCUMENT_AI_LOCATION, processor_id)
    raw = documentai.RawDocument(content=content, mime_type=mime_type)
    request = documentai.ProcessRequest(name=name, raw_document=raw, imageless_mode=True)
    return client.process_document(request=request).document


def text_from_anchor(anchor, full_text):
    if not anchor or not anchor.text_segments:
        return ""
    parts = []
    for seg in anchor.text_segments:
        start = int(seg.start_index or 0)
        end = int(seg.end_index or 0)
        if end > start:
            parts.append(full_text[start:end])
    return "".join(parts).strip()


def normalize_cell(value):
    if value is None:
        return ""
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def format_table_ascii(rows):
    """Tabela ASCII completa, sem truncamento."""
    if not rows:
        return ""
    max_cols = max((len(r) for r in rows), default=0)
    if max_cols == 0:
        return ""
    normalized = []
    for row in rows:
        cells = [normalize_cell(v) for v in row]
        cells += [""] * (max_cols - len(cells))
        normalized.append(cells)
    widths = [max(len(row[c]) for row in normalized) for c in range(max_cols)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    for row in normalized:
        out.append("|" + "|".join(f" {row[c].ljust(widths[c])} " for c in range(max_cols)) + "|")
        out.append(sep)
    return "\n".join(out)


def rect_intersection_ratio(a: fitz.Rect, b: fitz.Rect):
    inter = a & b
    if inter.is_empty or a.get_area() <= 0:
        return 0.0
    return inter.get_area() / a.get_area()


def extract_native_items(page):
    table_items, table_rects = [], []
    try:
        finder = page.find_tables()
        for table in finder.tables:
            bbox = fitz.Rect(table.bbox)
            rows = table.extract() or []
            rendered = format_table_ascii(rows)
            if rendered:
                table_rects.append(bbox)
                table_items.append({"y": bbox.y0, "x": bbox.x0, "bbox": bbox, "type": "table", "text": rendered})
    except Exception as exc:
        logger.debug("Tabela nativa não detectada: %s", exc)

    text_items = []
    for block in page.get_text("blocks", sort=False):
        if len(block) < 5:
            continue
        rect = fitz.Rect(block[:4])
        text = (block[4] or "").strip()
        if not text:
            continue
        if any(rect_intersection_ratio(rect, tr) >= 0.55 for tr in table_rects):
            continue
        text_items.append({"y": rect.y0, "x": rect.x0, "bbox": rect, "type": "text", "text": text})

    items = text_items + table_items
    items.sort(key=lambda i: (round(i["y"], 1), round(i["x"], 1)))
    return items, len(table_items)


def page_image_rects(page):
    rects, seen = [], set()
    for image in page.get_images(full=True):
        xref = image[0]
        try:
            found = page.get_image_rects(xref)
        except Exception:
            found = []
        for r in found:
            r = fitz.Rect(r)
            if r.is_empty or r.width < 2 or r.height < 2:
                continue
            key = tuple(round(v, 1) for v in (r.x0, r.y0, r.x1, r.y1))
            if key not in seen:
                seen.add(key)
                rects.append(r)
    return rects


def render_png(page, clip=None, dpi=RENDER_DPI):
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), clip=clip, alpha=False)
    return pix.tobytes("png")


def png_is_blank(png_bytes):
    """Evita chamadas de OCR em páginas praticamente brancas."""
    data = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return False
    # Pixels realmente escuros; pequenas imperfeições do scanner não devem contar como conteúdo.
    dark_ratio = float(np.mean(image < 210))
    return dark_ratio < BLANK_DARK_PIXEL_RATIO


def png_has_table_grid(png_bytes):
    if not TABLE_FORM_PARSER:
        return False
    data = np.frombuffer(png_bytes, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return False
    h, w = image.shape[:2]
    if h < 80 or w < 80:
        return False
    binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 20), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 20)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk)
    hc, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    vc, _ = cv2.findContours(vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h_lines = [cv2.boundingRect(c) for c in hc if cv2.boundingRect(c)[2] >= w * TABLE_LINE_COVERAGE]
    v_lines = [cv2.boundingRect(c) for c in vc if cv2.boundingRect(c)[3] >= h * 0.12]
    return len(h_lines) >= TABLE_MIN_H and len(v_lines) >= TABLE_MIN_V


def layout_rect(layout):
    if not layout or not layout.bounding_poly:
        return None
    vertices = list(layout.bounding_poly.normalized_vertices or [])
    if not vertices:
        return None
    xs, ys = [v.x for v in vertices], [v.y for v in vertices]
    return (min(xs), min(ys), max(xs), max(ys))


def normalized_intersection(a, b):
    if not a or not b:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    area = (ax1 - ax0) * (ay1 - ay0)
    return ((ix1 - ix0) * (iy1 - iy0)) / area if area > 0 else 0.0


def form_parser_text(document):
    if not document.pages:
        return (document.text or "").strip(), 0
    page = document.pages[0]
    table_rects, items = [], []
    for table in page.tables:
        tr = layout_rect(table.layout)
        if tr:
            table_rects.append(tr)
        rows = []
        for row in table.header_rows:
            rows.append([text_from_anchor(c.layout.text_anchor, document.text) for c in row.cells])
        for row in table.body_rows:
            rows.append([text_from_anchor(c.layout.text_anchor, document.text) for c in row.cells])
        rendered = format_table_ascii(rows)
        if rendered:
            x, y = (tr[0], tr[1]) if tr else (0.0, 1.0)
            items.append({"x": x, "y": y, "text": rendered})

    candidates = list(getattr(page, "paragraphs", []) or []) or list(getattr(page, "lines", []) or [])
    for item in candidates:
        r = layout_rect(item.layout)
        if r and any(normalized_intersection(r, tr) >= 0.55 for tr in table_rects):
            continue
        text = text_from_anchor(item.layout.text_anchor, document.text).strip()
        if text:
            x, y = (r[0], r[1]) if r else (0.0, 0.0)
            items.append({"x": x, "y": y, "text": text})
    items.sort(key=lambda i: (i["y"], i["x"]))
    return "\n\n".join(i["text"] for i in items).strip(), len(page.tables)


def smart_ocr(png_bytes, client):
    if FORM_PROCESSOR_ID and png_has_table_grid(png_bytes):
        try:
            doc = process_bytes(png_bytes, "image/png", FORM_PROCESSOR_ID, client)
            return form_parser_text(doc)
        except Exception as exc:
            logger.warning("Form Parser falhou; fallback para Enterprise OCR: %s", exc)
    doc = process_bytes(png_bytes, "image/png", OCR_PROCESSOR_ID, client)
    return (doc.text or "").strip(), 0


def classify_page(page):
    native = (page.get_text("text") or "").strip()
    images = page_image_rects(page)
    has_text = len(native) >= MIN_NATIVE_CHARS
    if has_text and images:
        return "mixed", native, images
    if has_text:
        return "digital", native, images
    return "image", native, images


def extract_page(page, client):
    page_type, native_text, images = classify_page(page)
    if page_type == "digital":
        items, _ = extract_native_items(page)
        return "\n\n".join(i["text"] for i in items).strip() or native_text

    if page_type == "image":
        png = render_png(page, clip=page.rect)
        if png_is_blank(png):
            return ""
        text, _ = smart_ocr(png, client)
        return text.strip()

    native_items, _ = extract_native_items(page)
    all_items = list(native_items)
    native_tables = [i["bbox"] for i in native_items if i["type"] == "table"]
    for rect in images:
        if any(rect_intersection_ratio(rect, table_rect) >= 0.90 for table_rect in native_tables):
            continue
        try:
            png = render_png(page, clip=rect)
            if png_is_blank(png):
                continue
            text, _ = smart_ocr(png, client)
            if text.strip():
                all_items.append({"y": rect.y0, "x": rect.x0, "bbox": rect, "type": "image_ocr", "text": text.strip()})
        except Exception as exc:
            logger.warning("OCR de imagem falhou: %s", exc)
    all_items.sort(key=lambda i: (round(i["y"], 1), round(i["x"], 1)))
    return "\n\n".join(i["text"] for i in all_items if i.get("text", "").strip()).strip()


def process_pdf_to_txt(pdf_path: Path, output_path: Path, progress_callback=None):
    pdf = fitz.open(pdf_path)
    total = len(pdf)
    client = create_document_ai_client()
    sections = [f"Arquivo: {pdf_path.name}", f"Total de páginas: {total}"]
    try:
        for index in range(total):
            text = extract_page(pdf[index], client).strip()
            if not text:
                text = "PÁGINA EM BRANCO"
            sections.append(f"========== PÁGINA {index + 1} DE {total} ==========\n{text}")
            if progress_callback:
                progress_callback(index + 1, total)
    finally:
        pdf.close()
    output_path.write_text("\n\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return total
