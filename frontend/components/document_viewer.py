"""In-App Document Viewer Component for MedUnderwriter."""
from __future__ import annotations

import base64
import hashlib
from typing import Any
import streamlit as st

try:
    import pymupdf  # type: ignore
except ImportError:
    pymupdf = None

from api_client import api, APIError


def render_document_preview_content(
    doc_bytes: bytes,
    filename: str,
    doc_meta: dict[str, Any] | None = None,
) -> None:
    """Render document preview with PDF iframe, PyMuPDF image fallback, and metadata pane."""
    if not doc_bytes:
        st.warning("Document content is empty.")
        return

    meta = doc_meta or {}
    sha256 = hashlib.sha256(doc_bytes).hexdigest()
    file_size_kb = round(len(doc_bytes) / 1024, 1)

    # Top metadata pill bar
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.caption(f"**Filename:** {filename}")
    with col2:
        doc_type = meta.get("document_type") or "medical"
        st.caption(f"**Type:** {doc_type.upper()}")
    with col3:
        st.caption(f"**Size:** {file_size_kb} KB")
    with col4:
        st.caption(f"**SHA-256:** `{sha256[:12]}...`")

    st.download_button(
        label=f"⬇️ Download {filename}",
        data=doc_bytes,
        file_name=filename,
        mime="application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream",
        key=f"dl_{filename}_{sha256[:8]}",
    )

    is_pdf = filename.lower().endswith(".pdf")
    is_image = any(filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"])

    if is_pdf:
        view_mode = st.radio(
            "Rendering Mode",
            ["PDF Interactive Viewer", "Rendered Page Images (Fallback)", "Raw Extracted Text"],
            horizontal=True,
            key=f"mode_{filename}_{sha256[:8]}",
        )

        if view_mode == "PDF Interactive Viewer":
            base64_pdf = base64.b64encode(doc_bytes).decode("utf-8")
            pdf_iframe = (
                f'<iframe src="data:application/pdf;base64,{base64_pdf}" '
                f'width="100%" height="650px" type="application/pdf" '
                f'style="border: 1px solid #cbd5e1; border-radius: 8px;"></iframe>'
            )
            st.markdown(pdf_iframe, unsafe_allow_html=True)

        elif view_mode == "Rendered Page Images (Fallback)":
            if pymupdf is not None:
                try:
                    pdf_doc = pymupdf.open(stream=doc_bytes, filetype="pdf")
                    total_pages = len(pdf_doc)
                    st.info(f"Rendering {total_pages} pages via PyMuPDF...")
                    for page_num in range(total_pages):
                        page = pdf_doc.load_page(page_num)
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        st.caption(f"Page {page_num + 1} of {total_pages}")
                        st.image(img_bytes, width="stretch")
                    pdf_doc.close()
                except Exception as exc:
                    st.error(f"PyMuPDF rendering failed: {exc}")
            else:
                st.warning("PyMuPDF is not installed in the environment for page image rendering.")

        elif view_mode == "Raw Extracted Text":
            if pymupdf is not None:
                try:
                    pdf_doc = pymupdf.open(stream=doc_bytes, filetype="pdf")
                    full_text = []
                    for i, page in enumerate(pdf_doc):
                        full_text.append(f"--- Page {i+1} ---\n" + page.get_text())
                    pdf_doc.close()
                    st.text_area("Extracted OCR/Text", value="\n\n".join(full_text), height=500)
                except Exception as exc:
                    st.error(f"Failed to extract text: {exc}")
            else:
                st.info("PyMuPDF required to extract text directly from PDF.")

    elif is_image:
        st.image(doc_bytes, caption=filename, width="stretch")

    else:
        # Text/JSON/Other
        try:
            text_content = doc_bytes.decode("utf-8")
            st.code(text_content, language="json" if filename.lower().endswith(".json") else "text")
        except UnicodeDecodeError:
            st.warning("Binary document preview not available for this file type.")


@st.dialog("Document Viewer", width="large")
def open_document_viewer_dialog(
    case_id: str,
    document_id: str,
    filename: str,
    doc_meta: dict[str, Any] | None = None,
) -> None:
    """Standalone @st.dialog modal for viewing case documents from the Evidence workspace."""
    st.subheader(f"📄 {filename}")
    try:
        doc_bytes = api.get_case_document_content(case_id, document_id)
        render_document_preview_content(doc_bytes, filename, doc_meta)
    except APIError as exc:
        st.error(f"Failed to load document content: {exc}")
    except Exception as exc:
        st.error(f"Unexpected error loading document: {exc}")
