
import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
from supabase import create_client, Client
import re

QUOTA_PER_HA = 800
LOGO_PATH = "cloudia_logo.png"
LOGO_COCOA = "cocoasourcelogo.jpg"

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

def clean_farmer_id(val):
    if pd.isnull(val):
        return ""
    if not isinstance(val, str):
        val = str(val)
    val = val.encode("ascii", "ignore").decode("utf-8", "ignore")
    val = re.sub(r"[\s\u00a0\u200b\ufeff\u202f\u2060]+", "", val)
    return val.strip().lower()

@st.cache_data
def load_farmer_data():
    all_rows = []
    limit = 1000
    offset = 0
    while True:
        response = supabase.table("farmers").select("farmer_id, cooperative, area_ha").range(offset, offset + limit - 1).execute()
        rows = response.data
        if not rows:
            break
        all_rows.extend(rows)
        offset += limit
    farmers_df = pd.DataFrame(all_rows)
    farmers_df.columns = farmers_df.columns.str.lower()
    farmers_df['farmer_id'] = farmers_df['farmer_id'].apply(clean_farmer_id)
    return farmers_df.drop_duplicates(subset='farmer_id', keep='last')

def delete_existing_delivery(lot_number, exporter_name):
    supabase.table("traceability").delete().match({
        "export_lot": lot_number,
        "exporter": exporter_name
    }).execute()

def save_delivery_to_supabase(df):
    df_for_db = df.copy()
    df_for_db.columns = df_for_db.columns.str.strip().str.lower().str.replace(" ", "_")
    df_for_db['farmer_id'] = df_for_db['farmer_id'].apply(clean_farmer_id)
    data = df_for_db.to_dict(orient="records")
    supabase.table("traceability").insert(data).execute()

def save_approval_to_db(lot_numbers, exporter_name, file_name, approved_by="CloudIA"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = {
        "created_at": timestamp,
        "lot_number": ", ".join(str(l) for l in lot_numbers),
        "exporter_name": exporter_name,
        "approved_by": approved_by,
        "file_name": file_name
    }
    supabase.table("approvals").insert(data).execute()

def merge_farmers_with_delivery(farmers_df, delivery_df):
    delivery_df['farmer_id'] = delivery_df['farmer_id'].apply(clean_farmer_id)
    farmers_df['farmer_id'] = farmers_df['farmer_id'].apply(clean_farmer_id)
    merged_df = pd.merge(delivery_df, farmers_df, on='farmer_id', how='left')
    if 'area_ha' in merged_df.columns:
        merged_df['max_quota_kg'] = merged_df['area_ha'] * QUOTA_PER_HA
    else:
        merged_df['max_quota_kg'] = QUOTA_PER_HA
    merged_df['quota_used_pct'] = round(100 * merged_df['net_weight_kg'] / merged_df['max_quota_kg'], 1)
    merged_df['quota_status'] = merged_df['quota_used_pct'].apply(lambda x: "OK" if x <= 100 else "Exceeded")
    return merged_df

def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, lot_kg_summary, logo_path, logo_cocoa):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(200, 10, "Delivery Approval Certificate", ln=True, align="C")
    pdf.image(logo_path, x=10, y=20, w=40)
    pdf.image(logo_cocoa, x=60, y=20, w=40)
    pdf.set_y(60)
    pdf.set_font("Arial", "", 12)
    pdf.multi_cell(0, 10, f"Exporter: {exporter_name}")
    pdf.multi_cell(0, 10, f"Lots: {', '.join(str(l) for l in lot_numbers)}")
    pdf.multi_cell(0, 10, f"Total Farmers: {farmer_count}")
    pdf.multi_cell(0, 10, f"Total Net Weight: {round(total_kg / 1000, 2)} MT")  # Converted to Metric Tons
    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Lot Summary", ln=True)
    pdf.set_font("Arial", "", 12)
    for lot, kg in lot_kg_summary.items():
        pdf.cell(0, 10, f"{lot}: {round(kg / 1000, 2)} MT", ln=True)
    filename = f"approval_GFC_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(filename)
    return filename

col1, col2 = st.columns(2)
with col1:
    logo = Image.open(LOGO_PATH)
    st.image(logo, width=150)
with col2:
    cocoa_logo = Image.open(LOGO_COCOA)
    st.image(cocoa_logo, width=300)

st.title("CloudIA - Farmer Quota Verification System")

delivery_file = st.sidebar.file_uploader("Upload Delivery Template", type=["xlsx"])

farmers_df = load_farmer_data()

if delivery_file:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()
    uploaded_df['farmer_id'] = uploaded_df['farmer_id'].apply(clean_farmer_id)

    if 'exporter' not in uploaded_df.columns:
        st.error("Missing 'exporter' column in the Excel file.")
        st.stop()

    exporter_name = uploaded_df['exporter'].dropna().astype(str).iloc[0]
    st.success(f"Exporter from file: {exporter_name}")

    expected_columns = ['cooperative name', 'export lot n°/connaissement', 'date of purchase from cooperative',
                        'certification', 'farmer_id', 'farm_id', 'net weight (kg)', 'exporter']
    missing_columns = [col for col in expected_columns if col not in uploaded_df.columns]

    if missing_columns:
        st.error(f"Missing columns: {', '.join(missing_columns)}")
        st.stop()

    uploaded_df.rename(columns={
        'export lot n°/connaissement': 'export_lot',
        'net weight (kg)': 'net_weight_kg',
        'date of purchase from cooperative': 'purchase_date'
    }, inplace=True)

    uploaded_df['purchase_date'] = uploaded_df['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))

    if uploaded_df.isnull().values.any():
        st.error("Your file contains empty (null) cells.")
        st.stop()

    uploaded_df['exporter'] = exporter_name
    uploaded_df = uploaded_df.drop_duplicates(subset=['export_lot', 'exporter', 'farmer_id'], keep='last')

    for lot in uploaded_df['export_lot'].unique():
        delete_existing_delivery(lot, exporter_name)
    save_delivery_to_supabase(uploaded_df)

    merged_df = merge_farmers_with_delivery(farmers_df, uploaded_df)

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
                save_approval_to_db(
                    lot_numbers=lot_totals.index.tolist(),
                    exporter_name=exporter_name,
                    file_name=pdf_file
                )
                with open(pdf_file, "rb") as f:
                    st.download_button("Download Approval PDF", data=f, file_name=pdf_file, mime="application/pdf")
