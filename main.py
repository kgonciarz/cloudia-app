import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import os

# ---------------------- CONFIG ----------------------
QUOTA_PER_HA = 800
DB_FILE = "quota.db"
LOGO_PATH = "cloudia_logo.png"  # Make sure this file is in your directory
LOGO_COCOA = "cocoasourcelogo.jpg"
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

# ---------------------- LOAD FARMER DATA ----------------------
@st.cache_data
def load_farmer_data():
    farmers_df = pd.read_excel(FARMER_DB_PATH)
    farmers_df.columns = farmers_df.columns.str.lower()
    return farmers_df

@st.cache_data
def load_delivery_data(delivery_file):
    delivery_df = pd.read_excel(delivery_file)
    delivery_df.columns = delivery_df.columns.str.lower()
    return delivery_df

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
def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, logo_path=None, logo_cocoa=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # If CloudIA logo is provided, add it to the top left
    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=33)  # Adjust w as needed to control the size

    pdf.ln(20)  # Add some space between logos and text

    # If CocoaSource logo is provided, add it to the center of the page with a larger size
    if logo_cocoa and os.path.exists(logo_cocoa):
        pdf.image(logo_cocoa, x=(pdf.w - 110) / 2, y=3, w=110)  # Adjust w for larger size

    pdf.ln(30)  # Add some space after the CocoaSource logo

    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt="Delivery Approval Confirmation", ln=True, align='C')

    pdf.set_font("Arial", size=12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.ln(10)
    pdf.cell(200, 10, txt=f"Date: {now}", ln=True)
    
    # Join all lot numbers into a single string
    lot_numbers_str = ", ".join([str(x) for x in lot_numbers])  # Convert to string for consistency
    pdf.cell(200, 10, txt=f"Lot Numbers: {lot_numbers_str}", ln=True)

    pdf.cell(200, 10, txt=f"Exporter: {exporter_name}", ln=True)
    pdf.cell(200, 10, txt=f"Approved Farmers: {farmer_count}", ln=True)
    pdf.cell(200, 10, txt=f"Total Delivered (kg): {total_kg}", ln=True)
    pdf.cell(200, 10, txt="Approved by CloudIA", ln=True)
    pdf.ln(10)
    pdf.cell(200, 10, txt="All farmer IDs are valid and within quota limits.", ln=True)

    file_name = f"approval_{'_'.join(map(str, lot_numbers))}_{exporter_name}.pdf"  # Ensure correct formatting
    pdf.output(file_name)

    save_approval_to_db(lot_numbers_str, exporter_name, file_name)  # Store multiple lot numbers in the DB
    return file_name


# ---------------------- STREAMLIT UI ----------------------
init_db()

# Load the uploaded template
uploaded_file = st.file_uploader("Upload Template", type=["xlsx"])

if uploaded_file is not None:
    # Load the template file into a DataFrame
    uploaded_df = pd.read_excel(uploaded_file)

    # Standardize column names to lowercase and strip spaces
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()

    # Define expected columns (also in lowercase)
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

    # Check if the required columns are present in the dataframe
    missing_columns = [col for col in expected_columns.values() if col not in uploaded_df.columns]

    if missing_columns:
        st.error(f"Delivery file is missing the following required columns: {', '.join(missing_columns)}")
    else:
        st.success("All required columns are present!")

    # Show the updated dataframe
    st.write("Updated Template with Standardized Column Names:")
    st.dataframe(uploaded_df)

    # Title and Subtitle
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

        # Map the columns
        delivery_df.rename(columns={
            'cooperative_name': 'cooperative_name',
            'export_lot': 'export_lot',
            'date_of_purchase': 'date_of_purchase',
            'certification': 'certification',
            'farmer_id': 'farmer_id',
            'farm_id': 'farm_id',
            'net_weight': 'net_weight',
            'exporter': 'exporter'
        }, inplace=True)

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
        delivery_df = delivery_df.drop_duplicates(subset=['export_lot', 'exporter_name', 'farmer_id'], keep='last')

        # Insert into DB and process further
        lot_number = delivery_df['export_lot'].iloc[0]
        delete_existing_delivery(lot_number, exporter_name)
        save_delivery_to_db(delivery_df)

        # Calculate max quota for farmers
        farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.lower().str.strip()
        farmers_df['max_quota_kg'] = (farmers_df['area_ha'] * QUOTA_PER_HA).round(2)

        conn = sqlite3.connect(DB_FILE)
        total_df = pd.read_sql_query('''SELECT farmer_id, SUM(delivered_kg) as delivered_kg FROM deliveries GROUP BY farmer_id''', conn)
        conn.close()

        # Merge farmers with deliveries
        filtered_farmers_df = farmers_df[farmers_df['farmer_id'].isin(delivery_df['farmer_id'])]
        merged_df = pd.merge(filtered_farmers_df, total_df, on='farmer_id', how='left').fillna({'delivered_kg': 0})

        # Calculate quota used percentage and status
        merged_df['quota_used_pct'] = (merged_df['delivered_kg'] / merged_df['max_quota_kg']) * 100
        merged_df['quota_used_pct'] = merged_df['quota_used_pct'].round(2)
        merged_df['quota_status'] = merged_df['quota_used_pct'].apply(lambda x: "OK" if x <= 80 else ("Warning" if x <= 100 else "EXCEEDED"))

        unknown_farmers = delivery_df[~delivery_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()
        exceeded_df = merged_df[merged_df['quota_used_pct'] > 100]

        # Define all_ids_valid and any_quota_exceeded based on the conditions
        all_ids_valid = len(unknown_farmers) == 0
        any_quota_exceeded = not exceeded_df.empty

        if len(unknown_farmers) > 0:
            st.error("The following farmers are NOT in the database:")
            st.write(list(unknown_farmers))

        if not exceeded_df.empty:
            st.warning("These farmers have exceeded their quota:")
            st.dataframe(exceeded_df[['farmer_id', 'delivered_kg', 'max_quota_kg', 'quota_used_pct']])

        st.write("### Quota Overview")
        merged_df = merged_df.applymap(lambda x: str(x) if pd.notnull(x) else '')
        st.dataframe(merged_df[['farmer_id', 'area_ha', 'max_quota_kg', 'delivered_kg', 'quota_used_pct', 'quota_status']])

        # Now checking for file approval based on conditions
        if all_ids_valid and not any_quota_exceeded:
            st.success("File approved. All farmers valid and within quotas.")

        # Button to generate PDF
            if st.button("Generate Approval PDF"):
                total_kg = delivery_df['delivered_kg'].sum()  # Total delivered kilograms
                farmer_count = delivery_df['farmer_id'].nunique()  # Count of unique farmers

        # Generate PDF file with the required parameters, including both logos
                pdf_file = generate_pdf_confirmation(
                    lot_numbers=delivery_df['export_lot'].unique(),  # Pass all unique lot numbers
                    exporter_name=exporter_name,
                    farmer_count=farmer_count,
                    total_kg=total_kg,
                    logo_path=LOGO_PATH,  # CloudIA logo
                    logo_cocoa=LOGO_COCOA  # CocoaSource logo
                )

        # Open the generated PDF and allow the user to download it
                with open(pdf_file, "rb") as f:
                    st.download_button(
                        label="Download Approval PDF",  # Button label for download
                        data=f,  # PDF data
                        file_name=pdf_file,  # Use the generated PDF file name
                        mime="application/pdf"  # MIME type for PDF
                    )
        else:
    # Display a warning if the file is not approved due to unknown farmers or quota violations
            st.warning("File not approved – check for unknown farmers or quota violations.")
