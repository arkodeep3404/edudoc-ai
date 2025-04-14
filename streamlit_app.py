import streamlit as st
from pathlib import Path
import uuid
import os
import re
from iem_gen_ai_project import run_single_application_graph, handle_director_query, load_data, parse_criteria_pdf

UPLOAD_DIR = Path("uploaded_files")
UPLOAD_DIR.mkdir(exist_ok=True)

# === Session Reset ===
def reset_chat():
    st.session_state.messages = []
    st.session_state.step = 'welcome'  # Not 'upload_criteria'
    st.session_state.student_data = {
        "app_id": str(uuid.uuid4()),
        "name": None,
        "email": None,
        "marks10": None,
        "marks12": None,
        "wbjee_rank": None,
        "marksheet_pdf": None,
        "aadhaar_pdf": None,
        "aadhaar_name": None,
        "aadhaar_number": None,
        "loan_requested": False,
        "family_income_lpa": None,
        "marksheet_pdf_path": None,
        "aadhaar_pdf_path": None
    }


if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'step' not in st.session_state:
    st.session_state.step = 'upload_criteria'
if 'student_data' not in st.session_state:
    reset_chat()
if 'criteria_uploaded' not in st.session_state:
    st.session_state.criteria_uploaded = False

# === Admission Criteria Upload ===
if 'criteria_uploaded' not in st.session_state:
    st.session_state.criteria_uploaded = False

if not st.session_state.criteria_uploaded:
    st.title("📄 Upload Admission Criteria")
    criteria_file = st.file_uploader("Please upload the admission criteria PDF", type='pdf')

    if criteria_file:
        criteria_path = Path("uploaded_files") / "admission_criteria.pdf"
        with open(criteria_path, "wb") as f:
            f.write(criteria_file.getbuffer())

        # Import + parse logic
        from iem_gen_ai_project import parse_criteria_pdf
        parse_criteria_pdf(criteria_path)

        st.session_state.criteria_uploaded = True
        st.success("✅ Admission criteria uploaded and extracted successfully.")
        st.rerun()

    st.stop()  # 🛑 Do not continue until criteria is uploaded


# === Bot UI ===
st.title("Techdeck - Student Application & Loan Chatbot")
st.markdown("---")

# === Role Selection ===
if st.session_state.step == 'welcome':
    st.session_state.messages = []
    st.markdown("Welcome! Are you a student or an admin?")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🎓 Student"):
            st.session_state.step = 'get_name'
            st.rerun()
    with col2:
        if st.button("🛠 Admin"):
            st.session_state.step = 'admin_dashboard'
            st.rerun()

# === Form Inputs Step-by-Step ===
if st.session_state.step == 'get_name':
    name = st.text_input("What's your full name:")
    if name:
        st.session_state.student_data["name"] = name
        st.session_state.student_data["aadhaar_name"] = name
        st.session_state.student_data["applicant_name_marksheet"] = name
        st.session_state.step = 'get_marks10'
        st.rerun()

if st.session_state.step == 'get_marks10':
    marks10 = st.text_input("Enter your 10th PCM marks (%):")
    if marks10:
        st.session_state.student_data["marks10"] = float(marks10)
        st.session_state.step = 'get_marks12'
        st.rerun()

if st.session_state.step == 'get_marks12':
    marks12 = st.text_input("Enter your 12th PCM marks (%):")
    if marks12:
        st.session_state.student_data["marks12"] = float(marks12)
        st.session_state.step = 'get_wbjee_rank'
        st.rerun()

if st.session_state.step == 'get_wbjee_rank':
    rank = st.text_input("Enter your WBJEE rank:")
    if rank:
        st.session_state.student_data["wbjee_rank"] = int(rank)
        st.session_state.step = 'get_email'
        st.rerun()

if st.session_state.step == 'get_email':
    email = st.text_input("Enter your email address:")
    if email:
        st.session_state.student_data["email"] = email
        st.session_state.student_data["applicant_email"] = email
        st.session_state.step = 'upload_marksheet'
        st.rerun()

if st.session_state.step == 'upload_marksheet':
    marksheet = st.file_uploader("Upload your Marksheet (PDF only):", type='pdf')
    if marksheet:
        filename = f"{st.session_state.student_data['app_id']}_marksheet.pdf"
        path = UPLOAD_DIR / filename
        with open(path, "wb") as f:
            f.write(marksheet.getbuffer())
        st.session_state.student_data["marksheet_pdf_path"] = str(path)
        st.session_state.step = 'upload_aadhaar_pdf'
        st.rerun()

if st.session_state.step == 'upload_aadhaar_pdf':
    aadhaar = st.file_uploader("Upload your Aadhaar Card (PDF only):", type='pdf')
    if aadhaar:
        filename = f"{st.session_state.student_data['app_id']}_aadhaar.pdf"
        path = UPLOAD_DIR / filename
        with open(path, "wb") as f:
            f.write(aadhaar.getbuffer())
        st.session_state.student_data["aadhaar_pdf_path"] = str(path)
        st.session_state.step = 'enter_aadhaar_number'
        st.rerun()
        
if st.session_state.step == 'enter_aadhaar_number':
    aadhaar_number = st.text_input("Enter your 12-digit Aadhaar number:")

    if aadhaar_number and not re.match(r"^\d{12}$", aadhaar_number):
        st.warning("❌ Invalid Aadhaar number. Please enter exactly 12 digits.")
        st.stop()

    if aadhaar_number:
        st.session_state.student_data["aadhaar_number"] = aadhaar_number
        st.session_state.step = 'ask_loan'
        st.rerun()



if st.session_state.step == 'ask_loan':
    st.markdown("### 💰 Do you want to apply for a loan?")
    loan_choice = st.radio("Select one:", ["Yes", "No"], key="loan_choice_radio")

    if st.button("✅ Confirm Loan Choice"):
        st.session_state.student_data["loan_requested"] = (loan_choice == "Yes")
        if loan_choice == "Yes":
            st.session_state.step = 'ask_income'
        else:
            st.session_state.step = 'confirm_submission'
        st.rerun()
        
if st.session_state.step == 'confirm_submission':
    if st.button("📨 Submit Application"):
        run_single_application_graph(st.session_state.student_data)
        st.success("✅ Your application has been submitted or rejected based on criteria.")
        st.session_state.step = 'another_application'
        st.rerun()

if st.session_state.step == 'ask_income':
    income = st.text_input("Enter your family income (in LPA):")
    if income:
        st.session_state.student_data["family_income_lpa"] = float(income)
        run_single_application_graph(st.session_state.student_data)
        if float(income) <= 5.0:
            st.success("✅ Application submitted. Please email your ITR & income certificate to loan cell.")
        else:
            st.success("✅ Application submitted. (Loan not approved due to income.)")
        st.session_state.step = 'another_application'
        st.rerun()

if st.session_state.step == 'another_application':
    st.markdown("### 📝 Do you want to submit another application?")
    choice = st.radio("Select one:", ["Yes", "No"], key='another_app_choice')

    if choice == "Yes":
        if st.button("➡️ Start New Application"):
            reset_chat()
            st.rerun()

    elif choice == "No":
        st.info("✅ Thank you for your submission! You may now close this tab.")



# === Admin Dashboard ===
if st.session_state.step == 'admin_dashboard':
    st.header("📊 Admin Dashboard")
    data = load_data()
    st.metric("Total Applications", len(data['applications']))
    approved = [app for app in data['applications'] if app.get('loan_status') == "Approved"]
    st.metric("Loans Approved", len(approved))

    from pandas import DataFrame
    display_data = []
    for app in data['applications']:
        display_data.append({
            "App ID": app.get("app_id"),
            "Name": app.get("name") or app.get("applicant_name_marksheet"),
            "Email": app.get("applicant_email"),
            "10th %": app.get("marks", {}).get("class10_pcm_perc"),
            "12th %": app.get("marks", {}).get("class12_pcm_perc"),
            "WBJEE Rank": app.get("wbjee_rank"),
            "Aadhaar Name": app.get("name") or app.get("applicant_name_marksheet"),
            "Aadhaar Number": str(app.get("aadhaar_number")) if app.get("aadhaar_number") else "",
            "Validation": app.get("validation_status"),
            "Loan": app.get("loan_status")
        })

    st.subheader("📋 Application Summary")
    st.dataframe(DataFrame(display_data))

# === Debug Info ===
with st.expander("🛠 Debug: Show Collected Student Data"):
    st.json(st.session_state.student_data)

# === Sidebar Reset ===
st.sidebar.button("🔄 Reset Chat", on_click=reset_chat)
