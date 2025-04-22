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
    return farmers_df

# ---------------------- DELETE EXISTING DELIVERY ----------------------
def delete_existing_delivery(lot_number, exporter_name):
    supabase.table("traceability").delete().match({
        "lot_number": lot_number,
        "exporter_name": exporter_name
    }).execute()


# ---------------------- SAVE TO DB ----------------------
def save_delivery_to_supabase(df):
    df_for_db = df.copy()
    df_for_db = df_for_db.rename(columns={
        'cooperative name': 'cooperative_name',
        'export lot n°/connaissement': 'export_lot',
        'date of purchase from cooperative': 'purchase_date',
        'certification': 'certification',
        'farmer_id': 'farmer_id',
        'farm_id': 'farm_id',
        'net weight (kg)': 'net_weight_kg',
        'exporter': 'exporter'
    })
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

    # NOWE: wyswietl MT per Lot
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Delivered Weight per Lot:", ln=True)
    pdf.set_font("Arial", size=12)
    for lot, kg in lot_kg_summary.items():
        mt = round(kg / 1000, 2)  # Convert kg to MT
        pdf.cell(200, 10, txt=f"Lot {lot}: {mt} MT", ln=True)

    pdf.ln(10)
    pdf.cell(200, 10, txt="All farmer IDs are valid and within quota limits.", ln=True)

    file_name = f"approval_{'_'.join(map(str, lot_numbers))}_{exporter_name}.pdf"
    pdf.output(file_name)

    save_approval_to_db(lot_numbers_str, exporter_name, file_name)
    return file_name

# ---------------------- STREAMLIT UI ----------------------
#init_db()

# Logo and Title
col1, col2 = st.columns(2)
with col1:
    logo = Image.open(LOGO_PATH)
    st.image(logo, width=150)
with col2:
    cocoa_logo = Image.open(LOGO_COCOA)
    st.image(cocoa_logo, width=300)

st.markdown("### Approved by **CloudIA**", unsafe_allow_html=True)
st.title("CloudIA - Farmer Quota Verification System")

# ---------------------- LOAD FARMER DATABASE ----------------------
farmers_df = load_farmer_data()

# ---------------------- UPLOAD DELIVERY FILE ----------------------
delivery_file = st.sidebar.file_uploader("Upload Delivery Template", type=["xlsx"])
exporter_name = st.sidebar.text_input("Exporter Name")

if delivery_file and exporter_name:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()

    expected_columns = {
        'cooperative_name': 'cooperative name',
        'export_lot': 'export lot n°/connaissement',
        'date_of_purchase': 'date of purchase from cooperative',
        'certification': 'certification',
        'farmer_id': 'farmer_id',
        'farm_id': 'farm_id',
        'net_weight': 'net weight (kg)',
        'exporter': 'exporter'
    }

    missing_columns = [col for col in expected_columns.values() if col not in uploaded_df.columns]

    if missing_columns:
        st.error(f"Delivery file is missing the following required columns: {', '.join(missing_columns)}")
    else:
        st.success("All required columns are present!")

        if 'date of purchase from cooperative' in uploaded_df.columns:
            today_str = datetime.today().strftime('%Y-%m-%d')
            uploaded_df['date of purchase from cooperative'] = uploaded_df['date of purchase from cooperative'].fillna(today_str)

        if uploaded_df.isnull().values.any():
            st.error("Error: Your file contains empty (null) cells. Please correct the file and upload again.")
            st.stop()  # Stop further execution

        uploaded_df.rename(columns={
            'export lot n°/connaissement': 'lot_number',
            'net weight (kg)': 'delivered_kg'
        }, inplace=True)

        uploaded_df['farmer_id'] = uploaded_df['farmer_id'].astype(str).str.lower().str.strip()
        uploaded_df['exporter_name'] = exporter_name

        uploaded_df = uploaded_df.drop_duplicates(subset=['lot_number', 'exporter_name', 'farmer_id'], keep='last')

        for lot in uploaded_df['lot_number'].unique():
            delete_existing_delivery(lot, exporter_name)
        save_delivery_to_supabase(uploaded_df)

        farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.lower().str.strip()
        farmers_df['max_quota_kg'] = (farmers_df['area_ha'] * QUOTA_PER_HA).round(2)

        conn = sqlite3.connect(DB_FILE)
        total_df = pd.read_sql_query('''SELECT farmer_id, SUM(delivered_kg) as delivered_kg FROM deliveries GROUP BY farmer_id''', conn)
        conn.close()

        filtered_farmers_df = farmers_df[farmers_df['farmer_id'].isin(uploaded_df['farmer_id'])]
        merged_df = pd.merge(filtered_farmers_df, total_df, on='farmer_id', how='left').fillna({'delivered_kg': 0})

        merged_df['quota_used_pct'] = (merged_df['delivered_kg'] / merged_df['max_quota_kg']) * 100
        merged_df['quota_used_pct'] = merged_df['quota_used_pct'].round(2)
        merged_df['quota_status'] = merged_df['quota_used_pct'].apply(lambda x: "OK" if x <= 80 else ("Warning" if x <= 100 else "EXCEEDED"))

        unknown_farmers = uploaded_df[~uploaded_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()
        exceeded_df = merged_df[merged_df['quota_used_pct'] > 100]

        all_ids_valid = len(unknown_farmers) == 0
        any_quota_exceeded = not exceeded_df.empty

        if unknown_farmers.size > 0:
            st.error("The following farmers are NOT in the database:")
            st.write(list(unknown_farmers))

        if not exceeded_df.empty:
            st.warning("These farmers have exceeded their quota:")
            st.dataframe(exceeded_df[['farmer_id', 'delivered_kg', 'max_quota_kg', 'quota_used_pct']])

        st.write("### Quota Overview")
        st.dataframe(merged_df[['farmer_id', 'area_ha', 'max_quota_kg', 'delivered_kg', 'quota_used_pct', 'quota_status']])

        if all_ids_valid and not any_quota_exceeded:
    # Check total delivered kg per lot
            lot_totals = uploaded_df.groupby('lot_number')['delivered_kg'].sum()
            lot_status_ok = lot_totals.between(21000, 29000).all()  # Between 21 MT and 29 MT

            if lot_status_ok:
                st.success("File approved. All farmers valid, quotas OK, and delivered kg per lot within allowed range.")
                if st.button("Generate Approval PDF"):
                    lot_totals = uploaded_df.groupby('lot_number')['delivered_kg'].sum()
                    total_mt = sum(round(kg / 1000, 2) for kg in lot_totals.values)  # <<< NOWE
                    total_kg = int(total_mt * 1000)

                    farmer_count = uploaded_df['farmer_id'].nunique()

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
                st.write("Delivered kg per lot summary:")
                st.dataframe(lot_totals)

        else:
            st.warning("File not approved – check for unknown farmers or quota violations.")



# ---------------------- ADMIN PANEL ----------------------
with st.expander("Admin Panel – View Delivery & Approval History"):
    st.image(LOGO_COCOA, width=250)
    password = st.text_input("Enter admin password:", type="password")
    if password == "123":
        st.success("Access granted!")
        wipe_password = st.text_input("Enter special password to clear all data:", type="password")
        if wipe_password == "321":
            if st.button("Clear All Data"):
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM deliveries")
                cursor.execute("DELETE FROM approvals")
                conn.commit()
                conn.close()
                st.success("Database has been cleared!")

        conn = sqlite3.connect(DB_FILE)
        deliveries_df = pd.read_sql_query("SELECT * FROM deliveries", conn)
        approvals_df = pd.read_sql_query("SELECT * FROM approvals", conn)
        conn.close()
        st.subheader("Delivery History")
        st.dataframe(deliveries_df)
        st.subheader("Approval History")
        st.dataframe(approvals_df)
    elif password:
        st.error("Incorrect password")

if st.button("🔌 Test connection"):
    try:
        res = supabase.table("traceability").select("*").limit(1).execute()
        st.success("✅ Supabase API działa!")
    except Exception as e:
        st.error(f"❌ Błąd połączenia z Supabase: {e}")
