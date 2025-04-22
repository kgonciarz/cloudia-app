import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import os
from supabase import create_client, Client

# ---------------------- CONFIG ----------------------
QUOTA_PER_HA = 800
LOGO_PATH = "cloudia_logo.png"
LOGO_COCOA = "cocoasourcelogo.jpg"
FARMER_DB_PATH = "farmer_database.xlsx"

# ---------------------- SUPABASE INIT ----------------------
@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

# ---------------------- CACHE DATA ----------------------
@st.cache_data
def load_farmer_data():
    farmers_df = pd.read_excel(FARMER_DB_PATH)
    farmers_df.columns = farmers_df.columns.str.lower()
    farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.lower().str.strip()
    farmers_df['max_quota_kg'] = (farmers_df['area_ha'] * QUOTA_PER_HA).round(2)
    return farmers_df

# ---------------------- DELETE EXISTING DELIVERY ----------------------
def delete_existing_delivery(lot_number, exporter_name):
    supabase.table("traceability").delete().match({
        "export_lot": lot_number,
        "exporter": exporter_name
    }).execute()

# ---------------------- SAVE TO DB ----------------------
def save_delivery_to_supabase(df):
    df_for_db = df.copy()
    df_for_db.columns = df_for_db.columns.str.strip().str.lower().str.replace(" ", "_")
    data = df_for_db.to_dict(orient="records")
    supabase.table("traceability").insert(data).execute()

# ---------------------- SAVE APPROVAL ----------------------
def save_approval_to_db(lot_number, exporter_name, file_name, approved_by="CloudIA"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    supabase.table("approvals").insert({
        "timestamp": timestamp,
        "lot_number": lot_number,
        "exporter_name": exporter_name,
        "approved_by": approved_by,
        "file_name": file_name
    }).execute()

# ---------------------- PDF GENERATOR ----------------------
def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, lot_kg_summary, logo_path=None, logo_cocoa=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=33)
    pdf.ln(20)
    if logo_cocoa and os.path.exists(logo_cocoa):
        pdf.image(logo_cocoa, x=(pdf.w - 110) / 2, y=3, w=110)
    pdf.ln(30)

    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Delivery Approval Confirmation", ln=True, align='C')
    pdf.set_font("Arial", size=12)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Date: {now}", ln=True)

    lot_numbers_str = ", ".join([str(x) for x in lot_numbers])
    pdf.cell(200, 10, txt=f"Lot Numbers: {lot_numbers_str}", ln=True)
    pdf.cell(200, 10, txt=f"Exporter: {exporter_name}", ln=True)
    pdf.cell(200, 10, txt=f"Approved Farmers: {farmer_count}", ln=True)
    pdf.cell(200, 10, txt=f"Total Delivered (kg): {total_kg}", ln=True)
    pdf.cell(200, 10, txt="Approved by CloudIA", ln=True)
    pdf.ln(10)

    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Delivered Weight per Lot:", ln=True)
    pdf.set_font("Arial", size=12)
    for lot, kg in lot_kg_summary.items():
        mt = round(kg / 1000, 2)
        pdf.cell(200, 10, txt=f"Lot {lot}: {mt} MT", ln=True)

    pdf.ln(10)
    pdf.cell(200, 10, txt="All farmer IDs are valid and within quota limits.", ln=True)

    file_name = f"approval_{'_'.join(map(str, lot_numbers))}_{exporter_name}.pdf"
    pdf.output(file_name)

    save_approval_to_db(lot_numbers_str, exporter_name, file_name)
    return file_name

# ---------------------- STREAMLIT UI ----------------------
col1, col2 = st.columns(2)
with col1:
    logo = Image.open(LOGO_PATH)
    st.image(logo, width=150)
with col2:
    cocoa_logo = Image.open(LOGO_COCOA)
    st.image(cocoa_logo, width=300)

st.markdown("### Approved by **CloudIA**", unsafe_allow_html=True)
st.title("CloudIA - Farmer Quota Verification System")

farmers_df = load_farmer_data()
delivery_file = st.sidebar.file_uploader("Upload Delivery Template", type=["xlsx"])
exporter_name = st.sidebar.text_input("Exporter Name")

if delivery_file and exporter_name:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()

    expected_columns = ['cooperative name', 'export lot n°/connaissement', 'date of purchase from cooperative',
                        'certification', 'farmer_id', 'farm_id', 'net weight (kg)', 'exporter']
    missing_columns = [col for col in expected_columns if col not in uploaded_df.columns]

    if missing_columns:
        st.error(f"Delivery file is missing the following required columns: {', '.join(missing_columns)}")
        st.stop()

    uploaded_df['purchase_date'] = uploaded_df['purchase_date'].fillna(
    datetime.today().strftime('%Y-%m-%d'))

    if uploaded_df.isnull().values.any():
        st.error("Error: Your file contains empty (null) cells. Please correct the file and upload again.")
        st.stop()

    uploaded_df.rename(columns={
        'export lot n°/connaissement': 'export_lot',
        'net weight (kg)': 'net_weight_kg',
        'date of purchase from cooperative': 'purchase_date'
    }, inplace=True)

    uploaded_df['farmer_id'] = uploaded_df['farmer_id'].astype(str).str.lower().str.strip()
    uploaded_df['exporter'] = exporter_name
    uploaded_df = uploaded_df.drop_duplicates(subset=['export_lot', 'exporter', 'farmer_id'], keep='last')

    for lot in uploaded_df['export_lot'].unique():
        delete_existing_delivery(lot, exporter_name)
    save_delivery_to_supabase(uploaded_df)

    trace_grouped = uploaded_df.groupby('farmer_id')['net_weight_kg'].sum().reset_index()
    merged_df = pd.merge(farmers_df, trace_grouped, on='farmer_id', how='left').fillna({'net_weight_kg': 0})
    merged_df['quota_used_pct'] = (merged_df['net_weight_kg'] / merged_df['max_quota_kg']) * 100
    merged_df['quota_status'] = merged_df['quota_used_pct'].apply(lambda x: "OK" if x <= 80 else ("Warning" if x <= 100 else "EXCEEDED"))

    unknown_farmers = uploaded_df[~uploaded_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()
    exceeded_df = merged_df[merged_df['quota_used_pct'] > 100]

    if unknown_farmers.size > 0:
        st.error("The following farmers are NOT in the database:")
        st.write(list(unknown_farmers))

    if not exceeded_df.empty:
        st.warning("These farmers have exceeded their quota:")
        st.dataframe(exceeded_df[['farmer_id', 'net_weight_kg', 'max_quota_kg', 'quota_used_pct']])

    st.write("### Quota Overview")
    st.dataframe(merged_df[['farmer_id', 'area_ha', 'max_quota_kg', 'net_weight_kg', 'quota_used_pct', 'quota_status']])

    all_ids_valid = len(unknown_farmers) == 0
    any_quota_exceeded = not exceeded_df.empty

    if all_ids_valid and not any_quota_exceeded:
        lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()
        lot_status_ok = lot_totals.between(21000, 29000).all()

        if lot_status_ok:
            st.success("File approved. All farmers valid, quotas OK, and delivered kg per lot within allowed range.")
            if st.button("Generate Approval PDF"):
                total_kg = int(lot_totals.sum())
                pdf_file = generate_pdf_confirmation(
                    lot_numbers=lot_totals.index.tolist(),
                    exporter_name=exporter_name,
                    farmer_count=uploaded_df['farmer_id'].nunique(),
                    total_kg=total_kg,
                    lot_kg_summary=lot_totals.to_dict(),
                    logo_path=LOGO_PATH,
                    logo_cocoa=LOGO_COCOA
                )
                with open(pdf_file, "rb") as f:
                    st.download_button(
                        label="Download Approval PDF",
                        data=f,
                        file_name=pdf_file,
                        mime="application/pdf"
                    )
        else:
            st.warning("File not approved – Delivered kg per lot must be between 21MT and 29MT.")
            st.dataframe(lot_totals)
    else:
        st.warning("File not approved – check for unknown farmers or quota violations.")
