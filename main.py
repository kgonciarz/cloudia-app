
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
        response = supabase.table("farmers").select("farmer_id, cooperative, area_ha").range(offset, offset + limit - 1).execute()
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

# DEBUG: Sprawdź obecność soc-02598
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
