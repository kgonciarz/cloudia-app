import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
import os

# ---------------------- CONFIG ----------------------
QUOTA_PER_HA = 800
DB_FILE = "quota.db"
LOGO_PATH = "cloudia_logo.png"  # Make sure this file is in your directory
FARMER_DB_PATH = "farmer_database.xlsx"  # Static farmer register file

# ---------------------- TRANSLATION DICTIONARY ----------------------
translations = {
    "en": {
        "title": "CloudIA - Farmer Quota Verification System",
        "subtitle": "Approved by **CloudIA**",
        "upload_delivery_file": "Upload Delivery File",
        "exporter_name": "Exporter Name",
        "error_invalid_file": "Delivery file must include 'farmer_id', 'poids net', 'lot'",
        "error_missing_values": "❌ Error: Missing values found in fields:",
        "error_empty_farmer_id": "❌ Error: Some farmer_id fields are empty.",
        "warning_exceeded_quota": "⚠️ These farmers have exceeded their quota:",
        "warning_file_not_approved": "🚫 File not approved – check for unknown farmers or quota violations.",
        "success_file_approved": "✅ File approved. All farmers valid and within quotas.",
        "button_generate_pdf": "📄 Generate Approval PDF",
        "button_download_pdf": "⬇️ Download Approval PDF",
        "admin_panel": "🔐 Admin Panel – View Delivery & Approval History",
        "admin_password": "Enter admin password:",
        "admin_access_granted": "Access granted ✅",
        "incorrect_password": "Incorrect password 🚫",
        "clear_all_data": "🧹 Clear All Data (Deliveries + Approvals)",
        "database_cleared": "✅ Database has been cleared!"
    },
    "fr": {
        "title": "CloudIA - Système de Vérification de Quotas Agricoles",
        "subtitle": "Approuvé par **CloudIA**",
        "upload_delivery_file": "Télécharger le fichier de livraison",
        "exporter_name": "Nom de l'exportateur",
        "error_invalid_file": "Le fichier de livraison doit inclure 'farmer_id', 'poids net', 'lot'",
        "error_missing_values": "❌ Erreur : Des valeurs manquantes ont été trouvées dans les champs:",
        "error_empty_farmer_id": "❌ Erreur : Certains champs 'farmer_id' sont vides.",
        "warning_exceeded_quota": "⚠️ Ces producteurs ont dépassé leur quota :",
        "warning_file_not_approved": "🚫 Fichier non approuvé – vérifiez les producteurs inconnus ou les violations de quota.",
        "success_file_approved": "✅ Fichier approuvé. Tous les producteurs sont valides et respectent les quotas.",
        "button_generate_pdf": "📄 Générer le PDF d'approbation",
        "button_download_pdf": "⬇️ Télécharger le PDF d'approbation",
        "admin_panel": "🔐 Panneau d'Admin – Historique des Livraisons et des Approbations",
        "admin_password": "Entrez le mot de passe admin :",
        "admin_access_granted": "Accès accordé ✅",
        "incorrect_password": "Mot de passe incorrect 🚫",
        "clear_all_data": "🧹 Effacer toutes les données (Livraisons + Approbations)",
        "database_cleared": "✅ La base de données a été effacée !"
    }
}

# ---------------------- SETUP LANGUAGE ----------------------
# Set the language based on user input
if "language" not in st.session_state:
    st.session_state.language = "en"  # Default language is English

# Language selector at the top-right corner
language = st.selectbox("Select Language", ["English", "Français"], key="language_selector", index=0 if st.session_state.language == "en" else 1)

# Update the session state if the user changes the language
if language == "English":
    st.session_state.language = "en"
else:
    st.session_state.language = "fr"

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

# ---------------------- CACHE DATA ----------------------
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

# ---------------------- PDF GENERATOR ----------------------
def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, logo_path=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=33)

    pdf.ln(20)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(200, 10, txt=translations[st.session_state.language]["button_generate_pdf"], ln=True, align='C')

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

# Logo and Title
logo = Image.open(LOGO_PATH)
st.image(logo, width=150)
st.markdown(f"### {translations[st.session_state.language]['subtitle']}", unsafe_allow_html=True)
st.title(translations[st.session_state.language]["title"])

# ---------------------- LOAD FARMER DATABASE ----------------------
farmers_df = pd.read_excel(FARMER_DB_PATH)
farmers_df.columns = farmers_df.columns.str.lower()

# ---------------------- UPLOAD DELIVERY FILE ----------------------
delivery_file = st.sidebar.file_uploader(translations[st.session_state.language]["upload_delivery_file"], type=["xlsx"])
exporter_name = st.sidebar.text_input(translations[st.session_state.language]["exporter_name"])

if delivery_file and exporter_name:
    delivery_df = pd.read_excel(delivery_file)
    delivery_df.columns = delivery_df.columns.str.lower()

    # Rename columns to match expected format
    delivery_df.rename(columns={'farmer_id': 'coode producteur', 'poids net': 'poids net', 'n° du lot': 'lot'}, inplace=True)

    if not {'coode producteur', 'poids net', 'lot'}.issubset(delivery_df.columns):
        st.error(translations[st.session_state.language]["error_invalid_file"])
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

        # Ensure lot_number and exporter_name are valid
        lot_number = delivery_df['lot_number'].iloc[0]
        if lot_number and exporter_name:
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
            st.success(translations[st.session_state.language]["success_file_approved"])

            if st.button(translations[st.session_state.language]["button_generate_pdf"]):
                total_kg = delivery_df['delivered_kg'].sum()
                farmer_count = delivery_df['farmer_id'].nunique()

        # Get the unique lot numbers
                lot_numbers = delivery_df['lot_number'].unique()  # Ensure lot numbers are in the right format (list/array)

                pdf_file = generate_pdf_confirmation(
                    lot_numbers=lot_numbers,  # Pass lot numbers as a list
                    exporter_name=exporter_name,
                    farmer_count=farmer_count,
                    total_kg=total_kg,
                    logo_path=LOGO_PATH
                )

                with open(pdf_file, "rb") as f:
                    st.download_button(
                        label=translations[st.session_state.language]["button_download_pdf"],
                        data=f,
                        file_name=pdf_file,
                        mime="application/pdf"
                    )
        else:
            st.warning(translations[st.session_state.language]["warning_file_not_approved"])

else:
    st.error("❌ Missing lot number or exporter name.")


# ---------------------- ADMIN PANEL ----------------------
with st.expander(translations[st.session_state.language]["admin_panel"]):
    password = st.text_input(translations[st.session_state.language]["admin_password"], type="password")
    if password == "123":
        st.success(translations[st.session_state.language]["admin_access_granted"])

        wipe_password = st.text_input("Enter special password to clear all data:", type="password")
        if wipe_password == "321":
            if st.button(translations[st.session_state.language]["clear_all_data"]):
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM deliveries")
                cursor.execute("DELETE FROM approvals")
                conn.commit()
                conn.close()
                st.success(translations[st.session_state.language]["database_cleared"])

        conn = sqlite3.connect(DB_FILE)
        deliveries_df = pd.read_sql_query("SELECT * FROM deliveries", conn)
        approvals_df = pd.read_sql_query("SELECT * FROM approvals", conn)
        conn.close()

        st.subheader("Delivery History")
        st.dataframe(deliveries_df)

        st.subheader("Approval History")
        st.dataframe(approvals_df)
    elif password:
        st.error(translations[st.session_state.language]["incorrect_password"])
