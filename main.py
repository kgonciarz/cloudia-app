
import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import os
from supabase import create_client, Client
import re

# ---------------------- CONFIG ----------------------
QUOTA_PER_HA = 800
LOGO_PATH = "cloudia_logo.png"
LOGO_COCOA = "cocoasourcelogo.jpg"

# ---------------------- SUPABASE INIT ----------------------

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

# ---------------------- UTIL ----------------------
def clean_farmer_id(val):
    if pd.isnull(val):
        return ""
    if not isinstance(val, str):
        val = str(val)
    val = val.encode("ascii", "ignore").decode("utf-8", "ignore")
    val = re.sub(r"[\s\u00a0\u200b\ufeff\u202f\u2060]+", "", val)
    return val.strip().lower()

# ---------------------- CACHE DATA ----------------------
@st.cache_data
def load_farmer_data():
    all_rows = []
    limit = 1000
    offset = 0

    while True:
        response = supabase.table("farmers").select("farmer_id").range(offset, offset + limit - 1).execute()

        rows = response.data
        if not rows:
            break
        all_rows.extend(rows)
        offset += limit

    farmers_df = pd.DataFrame(all_rows)
    farmers_df.columns = farmers_df.columns.str.lower()
    farmers_df['farmer_id'] = farmers_df['farmer_id'].apply(clean_farmer_id)
    farmers_df = farmers_df.drop_duplicates(subset='farmer_id', keep='last')
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
    df_for_db['farmer_id'] = df_for_db['farmer_id'].apply(clean_farmer_id)
    data = df_for_db.to_dict(orient="records")
    supabase.table("traceability").insert(data).execute()

# ---------------------- SAVE APPROVAL ----------------------
def save_approval_to_db(lot_number, exporter_name, file_name, approved_by="CloudIA"):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = {
        "created_at": timestamp,
        "lot_number": lot_number,
        "exporter_name": exporter_name,
        "approved_by": approved_by,
        "file_name": file_name
    }
    supabase.table("approvals").insert(data).execute()

# ---------------------- MERGE FARMERS + DELIVERY ----------------------
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

delivery_file = st.sidebar.file_uploader("Upload Delivery Template", type=["xlsx"])
exporter_name = st.sidebar.text_input("Exporter Name")

farmers_df = load_farmer_data()

st.subheader("🔍 DEBUG: Sprawdź obecność soc-02598 w farmers_df")

raw_farmer_ids = supabase.table("farmers").select("farmer_id").execute().data
raw_ids = [r['farmer_id'] for r in raw_farmer_ids if r['farmer_id'] is not None]

matches = [fid for fid in raw_ids if "02598" in fid]
st.write("Z bazy (surowe):", matches)

cleaned_matches = [clean_farmer_id(fid) for fid in raw_ids if "02598" in fid]
st.write("Po clean_farmer_id():", cleaned_matches)

if "soc-02598" in farmers_df['farmer_id'].values:
    st.success("✅ soc-02598 found in farmers_df")
else:
    st.error("❌ soc-02598 NOT found in farmers_df")


if delivery_file and exporter_name:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()
    uploaded_df['farmer_id'] = uploaded_df['farmer_id'].apply(clean_farmer_id)

    expected_columns = ['cooperative name', 'export lot n°/connaissement', 'date of purchase from cooperative',
                        'certification', 'farmer_id', 'farm_id', 'net weight (kg)', 'exporter']
    missing_columns = [col for col in expected_columns if col not in uploaded_df.columns]

    if missing_columns:
        st.error(f"Delivery file is missing the following required columns: {', '.join(missing_columns)}")
        st.stop()

    uploaded_df.rename(columns={
        'export lot n°/connaissement': 'export_lot',
        'net weight (kg)': 'net_weight_kg',
        'date of purchase from cooperative': 'purchase_date'
    }, inplace=True)

    uploaded_df['purchase_date'] = uploaded_df['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))

    if uploaded_df.isnull().values.any():
        st.error("Error: Your file contains empty (null) cells. Please correct the file and upload again.")
        st.stop()

    uploaded_df['exporter'] = exporter_name
    uploaded_df = uploaded_df.drop_duplicates(subset=['export_lot', 'exporter', 'farmer_id'], keep='last')

    for lot in uploaded_df['export_lot'].unique():
        delete_existing_delivery(lot, exporter_name)
    save_delivery_to_supabase(uploaded_df)

    merged_df = merge_farmers_with_delivery(farmers_df, uploaded_df)

    uploaded_df['farmer_id'] = uploaded_df['farmer_id'].apply(clean_farmer_id)
    farmers_df['farmer_id'] = farmers_df['farmer_id'].apply(clean_farmer_id)

    # DEBUG: Check for variations of "soc-02598"
    target_id = "soc-02598"
    match_in_db = [fid for fid in farmers_df['farmer_id'].unique() if target_id in fid or fid in target_id]
    match_in_upload = [fid for fid in uploaded_df['farmer_id'].unique() if target_id in fid or fid in target_id]
    st.info(f"Farmer ID check – looking for variations of '{target_id}'")
    st.write("🧩 Matches in DB:", match_in_db)
    st.write("🧾 Matches in Upload:", match_in_upload)

    unknown_farmers = uploaded_df[~uploaded_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()
    exceeded_df = merged_df[merged_df['quota_used_pct'] > 100]

    if unknown_farmers.size > 0:
        st.error("The following farmers are NOT in the database:")
        st.write(list(unknown_farmers))

    if not exceeded_df.empty:
        st.warning("These farmers have exceeded their quota:")
        st.dataframe(exceeded_df[['farmer_id', 'net_weight_kg', 'max_quota_kg', 'quota_used_pct']])

    st.write("### Quota Overview")
    if 'area_ha' in merged_df.columns:
        st.dataframe(merged_df[['farmer_id', 'area_ha', 'max_quota_kg', 'net_weight_kg', 'quota_used_pct', 'quota_status']])
    else:
        st.dataframe(merged_df[['farmer_id', 'max_quota_kg', 'net_weight_kg', 'quota_used_pct', 'quota_status']])

    all_ids_valid = len(unknown_farmers) == 0
    any_quota_exceeded = not exceeded_df.empty

    if all_ids_valid and not any_quota_exceeded:
        lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()
        lot_status_ok = lot_totals.between(21000, 29000).all()

        if lot_status_ok:
            st.success("File approved. All farmers valid, quotas OK, and delivered kg per lot within allowed range.")
