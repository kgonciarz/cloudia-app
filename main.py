import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import os
st.legacy_caching.clear_cache()
# ---------------------- CONFIG ----------------------
QUOTA_PER_HA = 800
DB_FILE = "quota.db"
LOGO_PATH = "cloudia_logo.png"  # Make sure this file is in your directory
FARMER_DB_PATH = "farmer_database.xlsx"  # Static farmer register file

# ---------------------- DATABASE INIT ----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS deliveries (
        lot_number TEXT,
        exporter_name TEXT,
        farmer_id TEXT,
        delivered_kg REAL,
        PRIMARY KEY (lot_number, exporter_name, farmer_id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS approvals (
        timestamp TEXT,
        lot_number TEXT,
        exporter_name TEXT,
        approved_by TEXT,
        file_name TEXT)''')
    conn.commit()
    conn.close()

# ---------------------- DELETE EXISTING DELIVERY ----------------------
def delete_existing_delivery(lot_number, exporter_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deliveries WHERE lot_number = ? AND exporter_name = ?", (lot_number, exporter_name))
    conn.commit()
    conn.close()

# ---------------------- SAVE TO DB ----------------------
def save_delivery_to_db(df):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    for _, row in df.iterrows():
        cursor.execute('''REPLACE INTO deliveries (lot_number, exporter_name, farmer_id, delivered_kg)
                        VALUES (?, ?, ?, ?)''', (row['lot_number'], row['exporter_name'], row['farmer_id'], row['delivered_kg']))
    conn.commit()
    conn.close()

# ---------------------- SAVE APPROVAL ----------------------
def save_approval_to_db(lot_number, exporter_name, file_name, approved_by="CloudIA"):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''INSERT INTO approvals (timestamp, lot_number, exporter_name, approved_by, file_name)
                    VALUES (?, ?, ?, ?, ?)''', (timestamp, lot_number, exporter_name, approved_by, file_name))
    conn.commit()
    conn.close()

# ---------------------- PDF GENERATOR ----------------------
def generate_pdf_confirmation(lot_number, exporter_name, farmer_count, total_kg, logo_path=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=33)

    pdf.ln(20)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Delivery Approval Confirmation", ln=True, align='C')

    pdf.set_font("Arial", size=12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Date: {now}", ln=True)
    pdf.cell(200, 10, txt=f"Lot Number: {lot_number}", ln=True)
    pdf.cell(200, 10, txt=f"Exporter: {exporter_name}", ln=True)
    pdf.cell(200, 10, txt=f"Approved Farmers: {farmer_count}", ln=True)
    pdf.cell(200, 10, txt=f"Total Delivered (kg): {total_kg}", ln=True)
    pdf.cell(200, 10, txt="Approved by CloudIA", ln=True)
    pdf.ln(10)
    pdf.cell(200, 10, txt="All farmer IDs are valid and within quota limits.", ln=True)

    file_name = f"approval_{lot_number}_{exporter_name}.pdf"
    pdf.output(file_name)

    save_approval_to_db(lot_number, exporter_name, file_name)
    return file_name

# ---------------------- STREAMLIT UI ----------------------
init_db()

# Logo and Title
logo = Image.open(LOGO_PATH)
st.image(logo, width=150)
st.markdown("### Approved by **CloudIA**", unsafe_allow_html=True)
st.title("CloudIA - Farmer Quota Verification System")

# ---------------------- LOAD FARMER DATABASE ----------------------
farmers_df = pd.read_excel(FARMER_DB_PATH)
farmers_df.columns = farmers_df.columns.str.lower()

# ---------------------- UPLOAD DELIVERY FILE ----------------------
delivery_file = st.sidebar.file_uploader("Upload Delivery File", type=["xlsx"])
exporter_name = st.sidebar.text_input("Exporter Name")

if delivery_file and exporter_name:
    delivery_df = pd.read_excel(delivery_file)
    delivery_df.columns = delivery_df.columns.str.lower()

    # Rename columns to match expected format
    delivery_df.rename(columns={'farmer_id': 'coode producteur', 'poids net': 'poids net', 'n° du lot': 'lot'}, inplace=True)

    if not {'coode producteur', 'poids net', 'lot'}.issubset(delivery_df.columns):
        st.error("Delivery file must include 'coode producteur', 'poids net', 'lot'")
    else:
        # Standardize column names
        delivery_df = delivery_df.rename(columns={
            'coode producteur': 'farmer_id',
            'poids net': 'delivered_kg',
            'lot': 'lot_number'
        })

        # Clean all text fields and remove any non-UTF-8 characters
        def clean_text(value):
            if isinstance(value, str):
                return value.encode('utf-8', 'ignore').decode('utf-8', 'ignore')
            return value

        # Apply the cleaning function
        delivery_df = delivery_df.applymap(clean_text)

        # Add exporter name and process the file
        delivery_df['exporter_name'] = exporter_name
        delivery_df['farmer_id'] = delivery_df['farmer_id'].astype(str).str.lower().str.strip()
        delivery_df = delivery_df.drop_duplicates(subset=['lot_number', 'exporter_name', 'farmer_id'], keep='last')

        # Insert into DB and process further
        lot_number = delivery_df['lot_number'].iloc[0]
        delete_existing_delivery(lot_number, exporter_name)
        save_delivery_to_db(delivery_df)

        # Calculate max quota for farmers
        farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.lower().str.strip()
        farmers_df['max_quota_kg'] = farmers_df['area_ha'] * QUOTA_PER_HA

        conn = sqlite3.connect(DB_FILE)
        total_df = pd.read_sql_query('''SELECT farmer_id, SUM(delivered_kg) as delivered_kg FROM deliveries GROUP BY farmer_id''', conn)
        conn.close()

        # Merge farmers with deliveries
        filtered_farmers_df = farmers_df[farmers_df['farmer_id'].isin(delivery_df['farmer_id'])]
        merged_df = pd.merge(filtered_farmers_df, total_df, on='farmer_id', how='left').fillna({'delivered_kg': 0})

        # Calculate quota used percentage and status
        merged_df['quota_used_pct'] = (merged_df['delivered_kg'] / merged_df['max_quota_kg']) * 100
        merged_df['quota_status'] = merged_df['quota_used_pct'].apply(lambda x: "OK" if x <= 80 else ("Warning" if x <= 100 else "EXCEEDED"))

        # Check for issues
        unknown_farmers = delivery_df[~delivery_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()
        exceeded_df = merged_df[merged_df['quota_used_pct'] > 100]

        if len(unknown_farmers) > 0:
            st.error("The following farmers are NOT in the database:")
            st.write(list(unknown_farmers))

        if not exceeded_df.empty:
            st.warning("These farmers have exceeded their quota:")
            st.dataframe(exceeded_df[['farmer_id', 'delivered_kg', 'max_quota_kg', 'quota_used_pct']])

        st.write("### Quota Overview")
        merged_df = merged_df.applymap(lambda x: str(x) if pd.notnull(x) else '')
        st.dataframe(merged_df[['farmer_id', 'area_ha', 'max_quota_kg', 'delivered_kg', 'quota_used_pct', 'quota_status']])

        all_ids_valid = len(unknown_farmers) == 0
        any_quota_exceeded = not exceeded_df.empty

        if all_ids_valid and not any_quota_exceeded:
            st.success("File approved. All farmers valid and within quotas.")

            if st.button("Generate Approval PDF"):
                total_kg = delivery_df['delivered_kg'].sum()
                farmer_count = delivery_df['farmer_id'].nunique()
                pdf_file = generate_pdf_confirmation(
                    lot_number=lot_number,
                    exporter_name=exporter_name,
                    farmer_count=farmer_count,
                    total_kg=total_kg,
                    logo_path=LOGO_PATH
                )

                with open(pdf_file, "rb") as f:
                    st.download_button(
                        label="Download Approval PDF",
                        data=f,
                        file_name=pdf_file,
                        mime="application/pdf"
                    )
        else:
            st.warning("File not approved – check for unknown farmers or quota violations.")

# ---------------------- ADMIN PANEL ----------------------
with st.expander("Admin Panel – View Delivery & Approval History"):
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
