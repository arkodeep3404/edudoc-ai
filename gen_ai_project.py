import os
import json
import uuid
from pathlib import Path
import re
from typing import Optional, List
from email.message import EmailMessage
import smtplib
from pydantic import BaseModel, Field
import PyPDF2
from datetime import datetime
from reportlab.pdfgen import canvas

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph

# === Credentials ===
os.environ["OPENAI_API_KEY"] = "sk-..."  # Replace with your OpenAI API Key
SENDER_EMAIL = "..........@............"
SENDER_PASSWORD = ".................."

# === Constants ===
DATA_FILE = "admission_data_v2.json"
BACKUP_FILE = "admission_data_backup.json"
UPLOAD_DIR = "uploaded_files"
Path(UPLOAD_DIR).mkdir(exist_ok=True)

# === Default Structures ===
DEFAULT_DATA_STRUCTURE = {
    "applications": [],
    "eligibility_criteria": {
        "min_class10_pcm_perc": 60,
        "min_class12_pcm_perc": 60,
        "max_wbjee_rank": 10000,
        "max_income_for_loan_lpa": 5.0,
        "required_docs": ["Marksheet", "Aadhaar"]
    },
    "university_capacity": 3,
    "loan_budget": 12000,
    "fee_amount": 5000,
    "director_log": [],
    "criteria_file_path": None
}

DEFAULT_APPLICATION_STRUCTURE = {
    "app_id": "",
    "applicant_name_marksheet": None,
    "applicant_email": None,
    "marks": {"class10_pcm_perc": None, "class12_pcm_perc": None},
    "wbjee_rank": None,
    "aadhaar_name": None,
    "aadhaar_number": None,
    "marksheet_pdf_path": None,
    "aadhaar_pdf_path": None,
    "family_income_lpa": None,
    "loan_requested": False,
    "extraction_status": "Pending",
    "validation_status": "Pending",
    "validation_reason": None,
    "shortlist_status": "Pending",
    "communication_status": "Not Sent",
    "loan_status": "Not Applicable",
    "loan_rejection_reason": None,
    "fee_slip_status": "Not Sent"
}

# === Data I/O ===
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump(DEFAULT_DATA_STRUCTURE, f, indent=4)
        return DEFAULT_DATA_STRUCTURE
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        with open(DATA_FILE, 'w') as f:
            json.dump(DEFAULT_DATA_STRUCTURE, f, indent=4)
        return DEFAULT_DATA_STRUCTURE

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    with open(BACKUP_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# === LangGraph State ===
class ProcessAppState(BaseModel):
    admission_data: dict
    current_app_index: int
    current_run_log: List[str] = Field(default_factory=list)
    extracted_marksheet_data: Optional[dict] = None
    extracted_aadhaar_data: Optional[dict] = None

# === PDF Text Extraction ===
def extract_text_from_pdf(pdf_path):
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        if text.strip():  # ✅ If text was found, return it
            return text
    except Exception as e:
        print(f"⚠️ PyMuPDF failed: {e}")

    # 🔁 OCR fallback for image-based PDFs
    try:
        from pdf2image import convert_from_path
        import pytesseract
        # Optional: Only if poppler not in PATH, set path like below
        # images = convert_from_path(pdf_path, poppler_path=r"C:\poppler\bin")
        images = convert_from_path(pdf_path)

        ocr_text = ""
        for img in images:
            ocr_text += pytesseract.image_to_string(img)
        return ocr_text
    except Exception as e:
        print(f"❌ OCR failed: {e}")
        return ""


# === Node: Extract Data ===
def data_extraction_node(state: ProcessAppState) -> ProcessAppState:
    i = state.current_app_index
    app = state.admission_data["applications"][i]

    marksheet_text = extract_text_from_pdf(app["marksheet_pdf_path"])
    aadhaar_text = extract_text_from_pdf(app["aadhaar_pdf_path"])

    print("📄 Extracted Marksheet Text:\n", marksheet_text[:500])
    print("📄 Extracted Aadhaar Text:\n", aadhaar_text[:500])

    # MARKSHEET extraction
    name_match = re.search(r"Name:\s*([A-Z][a-z]+)", marksheet_text)
    pcm10_match = re.search(r"Class 10 PCM Percentage:\s*([\d.]+)", marksheet_text)
    pcm12_match = re.search(r"Class 12 PCM Percentage:\s*([\d.]+)", marksheet_text)
    wbjee_match = re.search(r"WBJEE Rank:\s*(\d+)", marksheet_text)

    app["applicant_name_marksheet"] = name_match.group(1).strip() if name_match else "Unknown"

    if pcm10_match:
        app["marks"] = app.get("marks", {})
        app["marks"]["class10_pcm_perc"] = float(pcm10_match.group(1))

    if pcm12_match:
        app["marks"] = app.get("marks", {})
        app["marks"]["class12_pcm_perc"] = float(pcm12_match.group(1))

    if wbjee_match:
        app["wbjee_rank"] = int(wbjee_match.group(1))

    # AADHAAR extraction
    aadhaar_name_match = re.search(r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)", aadhaar_text)
    aadhaar_number_match = re.search(r"\d{4}\s\d{4}\s\d{4}", aadhaar_text)

    app["aadhaar_name"] = aadhaar_name_match.group(1).strip() if aadhaar_name_match else "Unknown"
    # ✅ Use already provided Aadhaar number from user
    if not app.get("aadhaar_number"):
        app["aadhaar_number"] = aadhaar_number_match.group(0).strip() if aadhaar_number_match else "XXXX-XXXX-XXXX"


    # Store extracted full text (optional)
    state.extracted_marksheet_data = {"text": marksheet_text}
    state.extracted_aadhaar_data = {"text": aadhaar_text}

    state.admission_data["applications"][i] = app
    state.current_run_log.append("🧾 PDF data extracted.")
    return state



# === Node: Validate ===
def validation_node(state: ProcessAppState) -> ProcessAppState:
    i = state.current_app_index
    app = state.admission_data["applications"][i]
    criteria = state.admission_data.get("eligibility_criteria", {})

    marks10 = app.get("marks", {}).get("class10_pcm_perc")
    marks12 = app.get("marks", {}).get("class12_pcm_perc")
    wbjee_rank = app.get("wbjee_rank")

    valid = (
        marks10 is not None and marks10 >= criteria.get("min_class10_pcm_perc", 60) and
        marks12 is not None and marks12 >= criteria.get("min_class12_pcm_perc", 60) and
        wbjee_rank is not None and wbjee_rank <= criteria.get("max_wbjee_rank", 10000)
    )

    if valid:
        app["validation_status"] = "Valid"
        state.current_run_log.append("✅ Application validated based on marks and rank. Please contact loan sanction cell with your last year ITR and income certificate.")
    else:
        app["validation_status"] = "Invalid"
        app["validation_reason"] = "Marks or WBJEE rank did not meet criteria"
        state.current_run_log.append("❌ Validation failed based on marks/rank.")

    state.admission_data["applications"][i] = app
    return state


# === Node: Email Communication ===
def communication_node(state: ProcessAppState) -> ProcessAppState:
    i = state.current_app_index
    app = state.admission_data["applications"][i]

    msg = EmailMessage()
    msg["Subject"] = f"Application Status - ID {app['app_id']}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = app["applicant_email"]

    # 🔍 Common part of the message
    content = f"Hello {app.get('name') or app.get('applicant_name_marksheet')},\n\n"
    content += f"Your application (ID: {app['app_id']}) has been {app['validation_status']}.\n"

    # ✅ Valid + Loan + Income < 5
    if app.get("validation_status") == "Valid" and app.get("loan_requested") and app.get("family_income_lpa", 10) < 5.0:
        content += (
            "\nSince your family income is below 5 LPA, please mail your last year ITR file and income certificate "
            "to the loan sanction cell to complete your loan processing."
        )
    # ✅ Valid + Loan + Income ≥ 5
    elif app.get("validation_status") == "Valid" and app.get("loan_requested") and app.get("family_income_lpa", 0) >= 5.0:
        content += "\nYou are not eligible for a loan due to income being 5 LPA or above."

    # ✅ Valid + No Loan
    elif app.get("validation_status") == "Valid" and not app.get("loan_requested"):
        content += "\nThank you for submitting your application. You have not requested a loan."

    # ❌ Invalid Case
    elif app.get("validation_status") == "Invalid":
        content += "\nUnfortunately, your application could not be validated due to missing or incorrect information."

    content += "\n\nThank you,\nAdmissions Team"
    msg.set_content(content)

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        app["communication_status"] = "Email Sent"
        state.current_run_log.append("📧 Email sent successfully.")
    except Exception as e:
        print(f"❌ Email failed: {e}")
        app["communication_status"] = "Failed to send"
        state.current_run_log.append(f"❌ Email error: {e}")

    state.admission_data["applications"][i] = app
    return state


# === Node: Loan and Fee Slip ===
def loan_processing_node(state: ProcessAppState) -> ProcessAppState:
    i = state.current_app_index
    app = state.admission_data["applications"][i]
    budget = state.admission_data.get("loan_budget", 0)

    if app.get("loan_requested"):
        income = app.get("family_income_lpa", 10)
        if income <= 5.0 and budget >= 5000:
            app["loan_status"] = "Approved"
            state.admission_data["loan_budget"] -= 5000
            state.current_run_log.append("🏦 Loan approved.")
        else:
            app["loan_status"] = "Rejected"
            app["loan_rejection_reason"] = "Income too high or insufficient budget"
            state.current_run_log.append("❌ Loan rejected.")
    else:
        app["loan_status"] = "Not Requested"
        state.current_run_log.append("💼 Loan not requested.")

    state.admission_data["applications"][i] = app
    return state


# === Build the LangGraph ===
process_app_workflow = StateGraph(ProcessAppState)
process_app_workflow.add_node("extract_data", data_extraction_node)
process_app_workflow.add_node("validate_application", validation_node)
process_app_workflow.add_node("communicate_status", communication_node)
process_app_workflow.add_node("check_loan_request", loan_processing_node)
process_app_workflow.set_entry_point("extract_data")
process_app_workflow.add_edge("extract_data", "validate_application")
process_app_workflow.add_edge("validate_application", "communicate_status")
process_app_workflow.add_edge("communicate_status", "check_loan_request")
process_app_workflow.set_finish_point("check_loan_request")
compiled_process_app_graph = process_app_workflow.compile()

# === Main Functions for Streamlit ===
def run_single_application_graph(student_data: dict):
    admission_data = load_data()
    new_app = DEFAULT_APPLICATION_STRUCTURE.copy()
    new_app["app_id"] = student_data["app_id"]
    new_app["marksheet_pdf_path"] = student_data.get("marksheet_pdf_path")
    new_app["aadhaar_pdf_path"] = student_data.get("aadhaar_pdf_path")
    new_app["loan_requested"] = student_data.get("loan_requested", False)
    new_app["family_income_lpa"] = student_data.get("family_income_lpa", None)
    new_app["applicant_email"] = student_data.get("email")
    new_app["aadhaar_number"] = student_data.get("aadhaar_number")
    admission_data["applications"].append(new_app)
    app_index = len(admission_data["applications"]) - 1
    state = {
        "admission_data": admission_data,
        "current_app_index": app_index,
        "current_run_log": [],
        "extracted_marksheet_data": None,
        "extracted_aadhaar_data": None
    }
    config = {"configurable": {"thread_id": f"app_process_{student_data['app_id']}"}}
    try:
        final_state = compiled_process_app_graph.invoke(state, config=config)
        save_data(final_state["admission_data"])
    except Exception as e:
        admission_data["director_log"].append(f"ERROR: {e}")
        save_data(admission_data)

def handle_director_query(query: str):
    try:
        current_data = load_data()
        data_summary = json.dumps(current_data, indent=2)
    except Exception as e:
        return "⚠️ Unable to load admission data."

    prompt = f"""
    You are a smart assistant for a university.
    Here is the current admission data:
    {data_summary}

    Now answer this question:
    {query}
    """

    try:
        llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content
    except Exception as e:
        return f"⚠️ Error generating response: {e}"

def parse_criteria_pdf(pdf_path):
    """
    Extract and update eligibility criteria from the uploaded admission criteria PDF.
    """
    text = extract_text_from_pdf(pdf_path)
    data = load_data()

    # Very basic rule extraction — you can improve with NLP or regex later
    match_10 = re.search(r'10th[^\\d]*(\\d{2})%', text)
    match_12 = re.search(r'12th[^\\d]*(\\d{2})%', text)
    match_rank = re.search(r'WBJEE[^\\d]*(\\d+)', text)
    match_income = re.search(r'income[^\\d]*(\\d+(\\.\\d+)?)\\s*LPA', text)

    if match_10:
        data['eligibility_criteria']['min_class10_pcm_perc'] = int(match_10.group(1))
    if match_12:
        data['eligibility_criteria']['min_class12_pcm_perc'] = int(match_12.group(1))
    if match_rank:
        data['eligibility_criteria']['max_wbjee_rank'] = int(match_rank.group(1))
    if match_income:
        data['eligibility_criteria']['max_income_for_loan_lpa'] = float(match_income.group(1))

    save_data(data)
    print("✅ Criteria updated from uploaded PDF.")
