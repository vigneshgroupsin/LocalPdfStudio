import io
import zipfile
from pathlib import Path
import streamlit as st
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageDraw
from pdf2docx import Converter

st.set_page_config(
    page_title="LocalPDF Studio Online",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- HELPER FUNCTIONS ---------------- #
def hex_to_rgb_norm(hex_str: str) -> tuple[float, float, float]:
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def parse_page_ranges(range_str: str, max_pages: int) -> list[int]:
    pages = []
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            pages.extend(range(max(0, start - 1), min(max_pages, end)))
        elif part.isdigit():
            p = int(part) - 1
            if 0 <= p < max_pages:
                pages.append(p)
    if not pages:
        raise ValueError("No valid pages matched the document length.")
    return pages


def render_pdf_page_image(pdf_bytes: bytes, page_idx: int, zoom: float = 1.25, rot: int = 0) -> Image.Image:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_idx]
        if rot:
            page.set_rotation((page.rotation + rot) % 360)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


# ---------------- SIDEBAR NAVIGATION ---------------- #
st.sidebar.title("📄 LocalPDF Studio")
st.sidebar.caption("Multi-User Web Edition • Private Per-Session Processing")

TOOLS = {
    "🗂️ Organize PDF": "organize",
    "✏️ Edit PDF (Insert Image, Text & Shapes)": "edit_pdf",
    "🔗 Merge PDF": "merge",
    "✂️ Split / Extract Pages": "split",
    "🗜️ Compress PDF (10%–90%)": "compress",
    "📸 PDF to JPG": "pdf2jpg",
    "📑 Images to PDF": "jpg2pdf",
    "📝 PDF to Word (.docx)": "pdf2word",
    "💧 Watermark PDF": "watermark",
    "🔒 Protect / Unlock PDF": "protect",
}

selected_label = st.sidebar.radio("Select a PDF Tool:", list(TOOLS.keys()))
tool = TOOLS[selected_label]

st.sidebar.markdown("---")
st.sidebar.info("🔒 Files are processed in your private browser session memory and never shared with other visitors.")


# ---------------- TOOL 1: ORGANIZE PDF ---------------- #
if tool == "organize":
    st.header("🗂️ Organize PDF")
    st.write("Reorder pages, rotate individual pages, or remove unwanted pages visually.")

    up_file = st.file_uploader("Upload a PDF file", type=["pdf"])
    if up_file:
        pdf_bytes = up_file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            total_pages = len(doc)

        if "org_state" not in st.session_state or st.session_state.get("org_name") != up_file.name:
            st.session_state.org_name = up_file.name
            st.session_state.org_state = [{"orig": i, "rot": 0} for i in range(total_pages)]

        pages_list = st.session_state.org_state

        c1, c2 = st.columns([1, 4])
        if c1.button("↩️ Reset Original Order"):
            st.session_state.org_state = [{"orig": i, "rot": 0} for i in range(total_pages)]
            st.rerun()

        cols = st.columns(4)
        for idx, item in enumerate(list(pages_list)):
            with cols[idx % 4]:
                with st.container(border=True):
                    st.markdown(f"**Page {idx + 1}** *(Orig #{item['orig'] + 1})*")
                    thumb = render_pdf_page_image(pdf_bytes, item["orig"], zoom=0.35, rot=item["rot"])
                    st.image(thumb, use_container_width=True)

                    b1, b2, b3, b4 = st.columns(4)
                    if b1.button("◀", key=f"org_l_{idx}", disabled=(idx == 0)):
                        pages_list[idx], pages_list[idx - 1] = pages_list[idx - 1], pages_list[idx]
                        st.rerun()
                    if b2.button("▶", key=f"org_r_{idx}", disabled=(idx == len(pages_list) - 1)):
                        pages_list[idx], pages_list[idx + 1] = pages_list[idx + 1], pages_list[idx]
                        st.rerun()
                    if b3.button("↻", key=f"org_rot_{idx}"):
                        pages_list[idx]["rot"] = (pages_list[idx]["rot"] + 90) % 360
                        st.rerun()
                    if b4.button("🗑️", key=f"org_del_{idx}", disabled=(len(pages_list) <= 1)):
                        pages_list.pop(idx)
                        st.rerun()

        if st.button("⚡ Build Organized PDF", type="primary"):
            src_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            out_doc = fitz.open()
            for entry in pages_list:
                out_doc.insert_pdf(src_doc, from_page=entry["orig"], to_page=entry["orig"])
                if entry["rot"]:
                    out_doc[-1].set_rotation((out_doc[-1].rotation + entry["rot"]) % 360)
            out_bytes = out_doc.tobytes(garbage=4, deflate=True)
            out_doc.close()
            src_doc.close()

            st.download_button(
                "💾 Download Organized PDF",
                data=out_bytes,
                file_name=f"{Path(up_file.name).stem}_organized.pdf",
                mime="application/pdf",
            )


# ---------------- TOOL 2: EDIT PDF (IMAGE, TEXT, SHAPES, CROP & ROTATE) ---------------- #
elif tool == "edit_pdf":
    st.header("✏️ Edit PDF — Insert Image, Text, Shapes, Crop & Rotate")

    up_pdf = st.file_uploader("Upload PDF to Edit", type=["pdf"])
    if up_pdf:
        pdf_bytes = up_pdf.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            num_pages = len(doc)
            page_rect = doc[0].rect
            pdf_w, pdf_h = page_rect.width, page_rect.height

        if "edit_items" not in st.session_state or st.session_state.get("edit_file") != up_pdf.name:
            st.session_state.edit_file = up_pdf.name
            st.session_state.edit_items = []
            st.session_state.edit_rotations = {}

        col_ctrl, col_prev = st.columns([1.15, 1.35])

        with col_ctrl:
            p_num = st.number_input("Select Page to Edit", min_value=1, max_value=num_pages, value=1)
            page_idx = int(p_num - 1)

            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                cur_rot = st.session_state.edit_rotations.get(page_idx, 0)
                doc[page_idx].set_rotation((doc[page_idx].rotation + cur_rot) % 360)
                pdf_w, pdf_h = doc[page_idx].rect.width, doc[page_idx].rect.height

            r1, r2 = st.columns(2)
            if r1.button("↻ Rotate Page 90°"):
                st.session_state.edit_rotations[page_idx] = (cur_rot + 90) % 360
                st.rerun()
            if r2.button("🔄 Clear All Edits"):
                st.session_state.edit_items = []
                st.session_state.edit_rotations = {}
                st.rerun()

            tab_img, tab_txt, tab_shp = st.tabs(["🖼️ Add Image", "🅰️ Add Text", "⬜ Add Shape"])

            with tab_img:
                up_img = st.file_uploader("Choose Image (PNG/JPG)", type=["png", "jpg", "jpeg", "webp"])
                if up_img:
                    raw_img_bytes = up_img.read()
                    pil_obj = ImageOps.exif_transpose(Image.open(io.BytesIO(raw_img_bytes)))
                    aspect = pil_obj.height / max(1, pil_obj.width)

                    ix = st.slider("X Position (pt)", 0, int(pdf_w), int(pdf_w * 0.15))
                    iy = st.slider("Y Position (pt)", 0, int(pdf_h), int(pdf_h * 0.15))
                    iw = st.slider("Width (pt)", 20, int(pdf_w), 160)
                    keep_ar = st.checkbox("Lock Aspect Ratio", value=True)
                    ih = int(iw * aspect) if keep_ar else st.slider("Height (pt)", 20, int(pdf_h), int(160 * aspect))

                    if st.button("➕ Place Image on Page", type="primary"):
                        st.session_state.edit_items.append({
                            "type": "image",
                            "page": page_idx,
                            "bytes": raw_img_bytes,
                            "pil": pil_obj,
                            "x": float(ix),
                            "y": float(iy),
                            "w": float(iw),
                            "h": float(ih),
                        })
                        st.rerun()

            with tab_txt:
                txt_val = st.text_input("Text Content", value="APPROVED")
                t1, t2 = st.columns(2)
                t_size = t1.slider("Font Size (pt)", 8, 96, 22)
                t_color = t2.color_picker("Text Color", "#E5322D")
                tx = st.slider("Text X (pt)", 0, int(pdf_w), int(pdf_w * 0.2))
                ty = st.slider("Text Y (pt)", 0, int(pdf_h), int(pdf_h * 0.2))

                if st.button("➕ Place Text on Page", type="primary") and txt_val.strip():
                    st.session_state.edit_items.append({
                        "type": "text",
                        "page": page_idx,
                        "text": txt_val,
                        "size": t_size,
                        "color": t_color,
                        "x": float(tx),
                        "y": float(ty),
                    })
                    st.rerun()

            with tab_shp:
                s_kind = st.selectbox("Shape Type", ["Rectangle", "Circle / Oval"])
                sc1, sc2, sc3 = st.columns(3)
                s_border = sc1.color_picker("Border Color", "#2563EB")
                s_fill = sc2.color_picker("Fill Color", "#93C5FD")
                s_use_fill = sc3.checkbox("Enable Fill", value=True)
                s_thick = st.slider("Border Thickness (pt)", 1, 12, 3)
                sx = st.slider("Shape X (pt)", 0, int(pdf_w), 60)
                sy = st.slider("Shape Y (pt)", 0, int(pdf_h), 60)
                sw = st.slider("Shape Width (pt)", 20, int(pdf_w), 150)
                sh = st.slider("Shape Height (pt)", 20, int(pdf_h), 90)

                if st.button("➕ Place Shape on Page", type="primary"):
                    st.session_state.edit_items.append({
                        "type": "rect" if "Rect" in s_kind else "oval",
                        "page": page_idx,
                        "border": s_border,
                        "fill": s_fill if s_use_fill else None,
                        "thick": s_thick,
                        "x": float(sx),
                        "y": float(sy),
                        "w": float(sw),
                        "h": float(sh),
                    })
                    st.rerun()

            if st.session_state.edit_items:
                st.subheader(f"Placed Items ({len(st.session_state.edit_items)})")
                if st.button("↩️ Undo Last Added Item"):
                    st.session_state.edit_items.pop()
                    st.rerun()

        # Live Composite Preview on Right Column
        with col_prev:
            st.subheader("Live Page Preview")
            preview_scale = 1.25
            base_img = render_pdf_page_image(
                pdf_bytes, page_idx, zoom=preview_scale, rot=st.session_state.edit_rotations.get(page_idx, 0)
            ).convert("RGBA")
            draw = ImageDraw.Draw(base_img)

            for item in st.session_state.edit_items:
                if item["page"] != page_idx:
                    continue
                px = int(item["x"] * preview_scale)
                py = int(item["y"] * preview_scale)
                if item["type"] == "image":
                    pw = max(10, int(item["w"] * preview_scale))
                    ph = max(10, int(item["h"] * preview_scale))
                    ov = item["pil"].convert("RGBA").resize((pw, ph))
                    base_img.paste(ov, (px, py), ov)
                elif item["type"] == "text":
                    draw.text((px, py), item["text"], fill=item["color"])
                elif item["type"] in ("rect", "oval"):
                    pw = max(10, int(item["w"] * preview_scale))
                    ph = max(10, int(item["h"] * preview_scale))
                    bbox = [px, py, px + pw, py + ph]
                    if item["type"] == "rect":
                        draw.rectangle(bbox, outline=item["border"], fill=item["fill"], width=item["thick"])
                    else:
                        draw.ellipse(bbox, outline=item["border"], fill=item["fill"], width=item["thick"])

            st.image(base_img, use_container_width=True)

            if st.button("💾 Generate & Download Edited PDF", type="primary", use_container_width=True):
                save_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                for p_i, r_deg in st.session_state.edit_rotations.items():
                    if r_deg:
                        save_doc[p_i].set_rotation((save_doc[p_i].rotation + r_deg) % 360)

                for item in st.session_state.edit_items:
                    pg = save_doc[item["page"]]
                    ox, oy = pg.rect.x0, pg.rect.y0
                    if item["type"] == "image":
                        rect = fitz.Rect(ox + item["x"], oy + item["y"], ox + item["x"] + item["w"], oy + item["y"] + item["h"])
                        pg.insert_image(rect, stream=item["bytes"], overlay=True, keep_proportion=False)
                    elif item["type"] == "text":
                        pg.insert_text(
                            fitz.Point(ox + item["x"], oy + item["y"] + item["size"]),
                            item["text"],
                            fontsize=item["size"],
                            color=hex_to_rgb_norm(item["color"]),
                            overlay=True,
                        )
                    elif item["type"] in ("rect", "oval"):
                        rect = fitz.Rect(ox + item["x"], oy + item["y"], ox + item["x"] + item["w"], oy + item["y"] + item["h"])
                        b_rgb = hex_to_rgb_norm(item["border"])
                        f_rgb = hex_to_rgb_norm(item["fill"]) if item["fill"] else None
                        if item["type"] == "rect":
                            pg.draw_rect(rect, color=b_rgb, fill=f_rgb, width=item["thick"], overlay=True)
                        else:
                            pg.draw_oval(rect, color=b_rgb, fill=f_rgb, width=item["thick"], overlay=True)

                final_bytes = save_doc.tobytes(garbage=4, deflate=True)
                save_doc.close()
                st.download_button(
                    "⬇️ Click Here to Save Edited PDF",
                    data=final_bytes,
                    file_name=f"{Path(up_pdf.name).stem}_edited.pdf",
                    mime="application/pdf",
                )


# ---------------- TOOL 3: MERGE PDF (VISUAL CARDS + ORDERING) ---------------- #
elif tool == "merge":
    st.header("🔗 Merge PDF Files")
    files = st.file_uploader("Upload 2 or more PDF files", type=["pdf"], accept_multiple_files=True)
    if files:
        file_map = {f.name: f.read() for f in files}
        ordered_names = st.multiselect(
            "Arrange Merge Order (remove & re-select to change order):",
            options=list(file_map.keys()),
            default=list(file_map.keys()),
        )

        cols = st.columns(min(4, max(1, len(ordered_names))))
        for idx, fname in enumerate(ordered_names):
            with cols[idx % len(cols)]:
                with st.container(border=True):
                    st.markdown(f"**#{idx + 1} — {fname[:22]}**")
                    thumb = render_pdf_page_image(file_map[fname], 0, zoom=0.32)
                    st.image(thumb, use_container_width=True)

        if len(ordered_names) >= 2 and st.button("⚡ Merge PDFs Now", type="primary"):
            out_doc = fitz.open()
            for fname in ordered_names:
                with fitz.open(stream=file_map[fname], filetype="pdf") as d:
                    out_doc.insert_pdf(d)
            merged_bytes = out_doc.tobytes(garbage=4, deflate=True)
            out_doc.close()
            st.download_button(
                "💾 Download Merged PDF", data=merged_bytes, file_name="merged.pdf", mime="application/pdf"
            )


# ---------------- TOOL 4: SPLIT / EXTRACT ---------------- #
elif tool == "split":
    st.header("✂️ Split / Extract PDF Pages")
    up = st.file_uploader("Upload PDF", type=["pdf"])
    if up:
        raw = up.read()
        with fitz.open(stream=raw, filetype="pdf") as doc:
            total = len(doc)
        st.info(f"Document has **{total}** pages.")
        rng = st.text_input("Pages to extract (e.g., 1-3, 5, 8-10)", value="1")
        if st.button("⚡ Extract Pages", type="primary"):
            try:
                pages = parse_page_ranges(rng, total)
                doc = fitz.open(stream=raw, filetype="pdf")
                doc.select(pages)
                out_b = doc.tobytes(garbage=4, deflate=True)
                doc.close()
                st.download_button(
                    "💾 Download Extracted PDF",
                    data=out_b,
                    file_name=f"{Path(up.name).stem}_extracted.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(str(e))


# ---------------- TOOL 5: COMPRESS PDF (10% - 90% SLIDER) ---------------- #
elif tool == "compress":
    st.header("🗜️ Compress PDF by Target Percentage")
    up = st.file_uploader("Upload PDF to Compress", type=["pdf"])
    if up:
        raw = up.read()
        orig_kb = len(raw) / 1024.0
        pct = st.slider("Target Size Reduction (%)", min_value=10, max_value=90, value=50, step=5)
        st.caption(f"Original Size: **{orig_kb:.1f} KB** → Estimated Target: **~{orig_kb * (1 - pct/100):.1f} KB**")

        if st.button("⚡ Compress PDF", type="primary"):
            target_dpi = int(220 - ((pct - 10) / 80.0) * 165)
            jpeg_quality = int(88 - ((pct - 10) / 80.0) * 63)
            with fitz.open(stream=raw, filetype="pdf") as doc:
                if pct <= 20:
                    comp_bytes = doc.tobytes(garbage=4, deflate=True, clean=True)
                else:
                    new_doc = fitz.open()
                    for page in doc:
                        pix = page.get_pixmap(dpi=target_dpi, alpha=False)
                        jpg_b = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
                        npg = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                        npg.insert_image(npg.rect, stream=jpg_b)
                    comp_bytes = new_doc.tobytes(garbage=4, deflate=True, clean=True)
                    new_doc.close()

            new_kb = len(comp_bytes) / 1024.0
            saved = max(0.0, (1.0 - new_kb / max(1.0, orig_kb)) * 100.0)
            st.success(f"Compressed from **{orig_kb:.1f} KB** to **{new_kb:.1f} KB** ({saved:.1f}% reduction)")
            st.download_button(
                "💾 Download Compressed PDF",
                data=comp_bytes,
                file_name=f"{Path(up.name).stem}_compressed.pdf",
                mime="application/pdf",
            )


# ---------------- TOOL 6: PDF TO JPG ---------------- #
elif tool == "pdf2jpg":
    st.header("📸 Convert PDF Pages to JPG (ZIP)")
    up = st.file_uploader("Upload PDF", type=["pdf"])
    dpi = st.select_slider("Render DPI", options=[100, 150, 200, 300], value=200)
    if up and st.button("⚡ Convert to JPGs", type="primary"):
        raw = up.read()
        zip_buf = io.BytesIO()
        with fitz.open(stream=raw, filetype="pdf") as doc, zipfile.ZipFile(zip_buf, "w") as zf:
            stem = Path(up.name).stem
            for i, page in enumerate(doc, start=1):
                pix = page.get_pixmap(dpi=dpi)
                zf.writestr(f"{stem}_page_{i}.jpg", pix.tobytes("jpeg"))
        st.download_button(
            "💾 Download All JPGs (.zip)",
            data=zip_buf.getvalue(),
            file_name=f"{Path(up.name).stem}_images.zip",
            mime="application/zip",
        )


# ---------------- TOOL 7: IMAGES TO PDF ---------------- #
elif tool == "jpg2pdf":
    st.header("📑 Convert Images to PDF")
    imgs = st.file_uploader("Upload JPG/PNG Images", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    if imgs and st.button("⚡ Create PDF", type="primary"):
        out_doc = fitz.open()
        for f in imgs:
            img_doc = fitz.open(stream=f.read(), filetype=Path(f.name).suffix.lstrip("."))
            pdf_b = img_doc.convert_to_pdf()
            out_doc.insert_pdf(fitz.open("pdf", pdf_b))
        res_b = out_doc.tobytes(garbage=4, deflate=True)
        out_doc.close()
        st.download_button("💾 Download Combined PDF", data=res_b, file_name="images.pdf", mime="application/pdf")


# ---------------- TOOL 8: PDF TO WORD ---------------- #
elif tool == "pdf2word":
    st.header("📝 Convert PDF to Editable Word (.docx)")
    up = st.file_uploader("Upload PDF", type=["pdf"])
    if up and st.button("⚡ Convert to Word", type="primary"):
        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_in:
            tmp_in.write(up.read())
            in_path = tmp_in.name
        out_path = in_path + ".docx"
        try:
            cv = Converter(in_path)
            cv.convert(out_path)
            cv.close()
            with open(out_path, "rb") as f:
                docx_bytes = f.read()
            st.download_button(
                "💾 Download Word Document (.docx)",
                data=docx_bytes,
                file_name=f"{Path(up.name).stem}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        finally:
            if os.path.exists(in_path):
                os.remove(in_path)
            if os.path.exists(out_path):
                os.remove(out_path)


# ---------------- TOOL 9: WATERMARK PDF ---------------- #
elif tool == "watermark":
    st.header("💧 Add Diagonal Watermark to PDF")
    up = st.file_uploader("Upload PDF", type=["pdf"])
    wm_text = st.text_input("Watermark Text", value="CONFIDENTIAL")
    if up and st.button("⚡ Apply Watermark", type="primary"):
        doc = fitz.open(stream=up.read(), filetype="pdf")
        for page in doc:
            r = page.rect
            page.insert_text(
                fitz.Point(r.width * 0.2, r.height * 0.5),
                wm_text or "CONFIDENTIAL",
                fontsize=44,
                rotate=45,
                color=(0.75, 0.75, 0.75),
                overlay=True,
            )
        out_b = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        st.download_button(
            "💾 Download Watermarked PDF",
            data=out_b,
            file_name=f"{Path(up.name).stem}_watermarked.pdf",
            mime="application/pdf",
        )


# ---------------- TOOL 10: PROTECT / UNLOCK ---------------- #
elif tool == "protect":
    st.header("🔒 Protect (Encrypt) or Unlock PDF")
    up = st.file_uploader("Upload PDF", type=["pdf"])
    mode = st.radio("Action:", ["Encrypt with Password (AES-256)", "Unlock (Remove Password)"])
    pwd = st.text_input("Password", type="password")
    if up and pwd and st.button("⚡ Process Security", type="primary"):
        doc = fitz.open(stream=up.read(), filetype="pdf")
        if "Encrypt" in mode:
            perm = int(fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY)
            out_b = doc.tobytes(
                encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=pwd, owner_pw=pwd, permissions=perm
            )
            st.download_button("💾 Download Protected PDF", data=out_b, file_name="protected.pdf", mime="application/pdf")
        else:
            if doc.is_encrypted and not doc.authenticate(pwd):
                st.error("Incorrect password.")
            else:
                out_b = doc.tobytes(encryption=fitz.PDF_ENCRYPT_NONE)
                st.download_button("💾 Download Unlocked PDF", data=out_b, file_name="unlocked.pdf", mime="application/pdf")
        doc.close()
