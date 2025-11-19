import sys
from pathlib import Path
from io import BytesIO

import streamlit as st
from docx import Document
from fpdf import FPDF
import unicodedata

# ---------------------------------------------------------------------
# Make sure we can import from src/
# ---------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
sys.path.append(str(SRC_DIR))

from config import OUT_DIR  # optional, if you want to inspect saved files
from rag_pipeline import generate_all_from_jd
try:
    from profile_config import USER_PROFILE
except ImportError:
    USER_PROFILE = None


# ---------------------------------------------------------------------
# Helpers: build DOCX / PDF from text
# ---------------------------------------------------------------------
def build_docx(text: str) -> bytes:
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()

def clean_text_for_pdf(text: str) -> str:
    # Normalise unicode
    text = unicodedata.normalize("NFKD", text)

    # Replace common “fancy” characters
    replacements = {
        "–": "-",   # en dash
        "—": "-",   # em dash
        "•": "-",   # bullet
        "“": '"',
        "”": '"',
        "’": "'",
        "…": "...",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)

    # Optional: drop anything still not representable in latin-1
    text = text.encode("latin-1", "ignore").decode("latin-1")
    return text




def build_pdf(text: str) -> bytes:
    text = clean_text_for_pdf(text)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Safer: write line by line
    for line in text.splitlines():
        pdf.multi_cell(0, 8, line)
        # Add a tiny gap between paragraphs
        pdf.ln(0.5)

    out = pdf.output(dest="S")  # can be str / bytes / bytearray depending on version

    # 🔒 Normalize to pure bytes
    if isinstance(out, bytearray):
        pdf_bytes = bytes(out)
    elif isinstance(out, bytes):
        pdf_bytes = out
    else:
        # probably str => encode to latin-1 as per fpdf docs
        pdf_bytes = out.encode("latin-1")

    # (Optional) sanity check in your console:
    # print("PDF length:", len(pdf_bytes))

    return pdf_bytes

# ---------------------------------------------------------------------
# Streamlit app
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="Job Application RAG Assistant",
    page_icon="🧠",
    layout="wide",
)

st.title("🧠 Job Application RAG Assistant")
st.caption("Paste a job description, generate tailored content, edit it, and download as DOCX/PDF.")

# Sidebar info
with st.sidebar:
    st.header("Profile")
    if USER_PROFILE:
        st.write(f"**Name:** {USER_PROFILE.get('name', '')}")
        st.write(f"**Title:** {USER_PROFILE.get('title', '')}")
        st.write(f"**Location:** {USER_PROFILE.get('location', '')}")
        st.write("**Links:**")
        for link in USER_PROFILE.get("links", []):
            st.write(f"- {link}")
    else:
        st.warning("USER_PROFILE not found. Fill in src/profile_config.py locally.")

    st.markdown("---")
    st.markdown(
        "💡 *Place your resume / project summaries as .txt/.md/.pdf in* "
        "`data/job_rag/profile_docs`."
    )


# ---------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------
if "jd_text" not in st.session_state:
    st.session_state.jd_text = ""

if "result" not in st.session_state:
    st.session_state.result = None

if "skills_text" not in st.session_state:
    st.session_state.skills_text = ""
if "cover_text" not in st.session_state:
    st.session_state.cover_text = ""
if "emails_text" not in st.session_state:
    st.session_state.emails_text = ""
if "ats_text" not in st.session_state:
    st.session_state.ats_text = ""
if "top_choice_text" not in st.session_state:
    st.session_state.top_choice_text = ""
if "short_recruiter_email_text" not in st.session_state:
    st.session_state.short_recruiter_email_text = ""


# ---------------------------------------------------------------------
# Input: Job description
# ---------------------------------------------------------------------
st.subheader("1️⃣ Paste Job Description")

jd_text = st.text_area(
    "Paste the full job description here:",
    value=st.session_state.jd_text,
    height=260,
    placeholder="Copy-paste the JD from LinkedIn / Seek / company website...",
)

st.session_state.jd_text = jd_text

col_generate, col_dummy = st.columns([1, 3])
with col_generate:
    generate_btn = st.button("⚙️ Generate Application Content", type="primary", use_container_width=True)


# ---------------------------------------------------------------------
# Run pipeline on click
# ---------------------------------------------------------------------
# if generate_btn:
#     if not jd_text.strip():
#         st.error("Please paste a job description first.")
#     else:
#         with st.spinner("Running RAG pipeline and generating content..."):
#             result = generate_all_from_jd(jd_text, save_to_disk=False)

#         st.session_state.result = result
#         st.session_state.skills_text = result["skills"]
#         st.session_state.cover_text = result["cover"]
#         st.session_state.emails_text = result["emails"]
#         st.session_state.ats_text = result["ats"]

#         st.success("Done! Scroll down to review, edit, and download your content.")






import traceback  # put this at the top of app.py if not already there

if generate_btn:
    if not jd_text.strip():
        st.error("Please paste a job description first.")
    else:
        with st.spinner("Running RAG pipeline and generating content..."):
            try:
                result = generate_all_from_jd(jd_text, save_to_disk=False)
            except Exception as e:
                st.error(f"Pipeline failed: {e}")
                traceback.print_exc()
                st.stop()

        # only runs if no exception
        st.session_state.result = result
        st.session_state.skills_text = result["skills"]
        st.session_state.cover_text = result["cover"]
        st.session_state.emails_text = result["emails"]
        st.session_state.ats_text = result["ats"]
        st.session_state.top_choice_text = result.get("top_choice", "")
        st.session_state.short_recruiter_email_text = result.get("short_recruiter_email", "")


        st.success("Done! Scroll down to review, edit, and download your content.")



# ---------------------------------------------------------------------
# Outputs: tabs with editable content + download buttons
# ---------------------------------------------------------------------
if st.session_state.result is not None:
    st.subheader("2️⃣ Review, Edit, and Download")

    tab_skills, tab_cover, tab_emails, tab_ats, tab_top_choice, tab_short_email = st.tabs(
    [
        "Skills & Keywords",
        "Cover Letter",
        "Emails",
        "ATS Summary",
        "Top-Choice Message",
        "Short Recruiter Email",
    ]
    )


    # ---- Skills & Keywords ----
    with tab_skills:
        st.markdown("### Skills & Keywords")
        skills_text = st.text_area(
            "Edit skills/keywords output:",
            value=st.session_state.skills_text,
            height=230,
        )
        st.session_state.skills_text = skills_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(skills_text),
                file_name="skills_keywords.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(skills_text),
                file_name="skills_keywords.pdf",
                mime="application/pdf",
            )

    # ---- Cover Letter ----
    with tab_cover:
        st.markdown("### Cover Letter")
        cover_text = st.text_area(
            "Edit cover letter:",
            value=st.session_state.cover_text,
            height=500,
        )
        st.session_state.cover_text = cover_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(cover_text),
                file_name="cover_letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(cover_text),
                file_name="cover_letter.pdf",
                mime="application/pdf",
            )

    # ---- Emails ----
    with tab_emails:
        st.markdown("### Email Templates")
        emails_text = st.text_area(
            "Edit email templates:",
            value=st.session_state.emails_text,
            height=500,
        )
        st.session_state.emails_text = emails_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(emails_text),
                file_name="emails.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(emails_text),
                file_name="emails.pdf",
                mime="application/pdf",
            )

    # ---- ATS Summary ----
    with tab_ats:
        st.markdown("### ATS Summary")
        ats_text = st.text_area(
            "Edit ATS summary:",
            value=st.session_state.ats_text,
            height=500,
        )
        st.session_state.ats_text = ats_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(ats_text),
                file_name="ats_summary.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(ats_text),
                file_name="ats_summary.pdf",
                mime="application/pdf",
            )

            # ---- Top-Choice Message (JD text box answer) ----
    with tab_top_choice:
        st.markdown("### Top-Choice Message (Application Text Box)")
        top_choice_text = st.text_area(
            "Edit the message you’ll paste into the 'Why is this your top choice & why are you a good fit?' box:",
            value=st.session_state.top_choice_text,
            height=500,
        )
        st.session_state.top_choice_text = top_choice_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(top_choice_text),
                file_name="top_choice_message.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(top_choice_text),
                file_name="top_choice_message.pdf",
                mime="application/pdf",
            )

    # ---- Short Recruiter Email ----
    with tab_short_email:
        st.markdown("### Short Recruiter Email")
        short_recruiter_email_text = st.text_area(
            "Edit the short recruiter email:",
            value=st.session_state.short_recruiter_email_text,
            height=500,
        )
        st.session_state.short_recruiter_email_text = short_recruiter_email_text

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Download as DOCX",
                data=build_docx(short_recruiter_email_text),
                file_name="short_recruiter_email.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        with col2:
            st.download_button(
                "📄 Download as PDF",
                data=build_pdf(short_recruiter_email_text),
                file_name="short_recruiter_email.pdf",
                mime="application/pdf",
            )


else:
    st.info("Paste a job description above and click **Generate Application Content** to get started.")




