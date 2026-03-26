import streamlit as st
import pandas as pd
from datetime import datetime
from fpdf import FPDF
from io import BytesIO
from PIL import Image
from supabase import create_client, Client
import re
import time
import base64
import math
from office365.runtime.auth.client_credential import ClientCredential
from office365.sharepoint.client_context import ClientContext
from urllib.parse import urlparse
st.set_page_config(page_title="CloudIA Quota Verifier", layout="centered")
# Language switcher
lang = st.sidebar.radio("🌐 Language / Langue", ["English", "Français"])

# Translation dictionary
def t(key):
    translations = {
        "upload_title": {
            "English": "📤 Drag and drop a verification file here",
            "Français": "📤 Glissez-déposez un fichier de vérification ici"
        },
        "or": {
            "English": "or",
            "Français": "ou"
        },
        "file_format_caption": {
            "English": "✅ Format: .xlsx | Max size: 200MB",
            "Français": "✅ Format : .xlsx | Taille max : 200 Mo"
        },
        "title": {
            "English": "☁ CloudIA – Farmer Quota Verification System",
            "Français": "☁ CloudIA – Système de Vérification des Quotas"
        },
        "generate_pdf": {
            "English": "Generate Approval PDF",
            "Français": "Générer le certificat PDF"
        },
        "download_pdf": {
            "English": "Download Approval PDF",
            "Français": "Télécharger le certificat PDF"
        },
        "insert_success": {
            "English": "✅ Data successfully inserted! {} new records added.",
            "Français": "✅ Données insérées avec succès ! {} nouveaux enregistrements ajoutés."
        },
        "insert_error": {
            "English": "❌ Error while inserting into traceability table",
            "Français": "❌ Erreur lors de l'insertion dans la table de traçabilité"
        },
        "approval_save_error": {
            "English": "❌ Error saving approval to the database",
            "Français": "❌ Erreur lors de l'enregistrement de l'approbation dans la base de données"
        },
        "file_approved": {
            "English": "✅ File approved. All farmers valid, quotas OK, and delivered kg per lot within allowed range.",
            "Français": "✅ Fichier approuvé. Tous les producteurs sont valides, les quotas sont respectés et les kg par lot sont dans la plage autorisée."
        },
        "rollback_error": {
            "English": "❌ Uploaded delivery has been rolled back due to validation errors. PDF cannot be generated.",
            "Français": "❌ La livraison téléversée a été annulée en raison d'erreurs de validation. Le certificat PDF ne peut pas être généré."
        },
        "lot_status_out_of_range": {
            "English": "### Lot Status Overview - Out of Range",
            "Français": "### Aperçu de l'état des lots - Hors plage autorisée"
        },
        "quota_warning_count": {
            "English": "⚠ {} farmers in the uploaded file have quota warnings or exceeded limits.",
            "Français": "⚠ {} producteurs du fichier ont des avertissements de quota ou ont dépassé les limites."
        },
        "quota_ok": {
            "English": "✅ All farmers in the uploaded file are within their assigned quotas.",
            "Français": "✅ Tous les producteurs du fichier respectent leurs quotas assignés."
        },
        "quota_overview_title": {
            "English": "### Quota Overview (Only Warnings and Exceeded)",
            "Français": "### Aperçu des quotas (avertissements et dépassements uniquement)"
        },
        "missing_farmer_id_column": {
            "English": "❌ quota_view does not contain 'farmer_id'. Columns returned: {}",
            "Français": "❌ La vue quota_view ne contient pas 'farmer_id'. Colonnes retournées : {}"
        },
        "unknown_farmers_error": {
            "English": "❌ The following farmers are NOT in the database:",
            "Français": "❌ Les producteurs suivants ne sont PAS présents dans la base de données :"
        },
        "missing_columns": {
            "English": "❌ Missing columns: {}",
            "Français": "❌ Colonnes manquantes : {}"
        },
        "missing_exporter_column": {
            "English": "❌ Missing 'exporter' column in the Excel file.",
            "Français": "❌ La colonne 'exporter' est manquante dans le fichier Excel."
        },
        "lot_too_low": {
            "English": "Too low",
            "Français": "Trop faible"
        },
        "lot_within_range": {
            "English": "Within range",
            "Français": "Dans la plage autorisée"
        },
        "saving": {
            "English": "💾 Saving data...",
            "Français": "💾 Sauvegarde des données..."
        }


    }
    return translations.get(key, {}).get(lang, key)




st.markdown("""
    <style>
    .stButton>button {
        color: white;
        background-color: #1c2b4a;
        border-radius: 8px;
        padding: 0.5em 2em;
        font-weight: bold;
        transition: 0.3s;
    }
    .stButton>button:hover {
        background-color: #36577c;
        color: white;
    }
    .stMarkdown h3 {
        color: #1c2b4a;
    }
    </style>
    """, unsafe_allow_html=True)

QUOTA_PER_HA = 800
LOGO_PATH = "cloudia_logo.png"
LOGO_COCOA = "edelsourcelogo.jpg"

@st.cache_resource
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = get_supabase()

@st.cache_data
def load_all_farmers():
    all_rows = []
    page_size = 1000
    last_farmer_id = None
    while True:
        query = supabase.table("farmers").select("*").limit(page_size).order("farmer_id")
        if last_farmer_id:
            query = query.gt("farmer_id", last_farmer_id)
        result = query.execute()
        rows = result.data
        if not rows:
            break
        all_rows.extend(rows)
        last_farmer_id = rows[-1]["farmer_id"]
    farmers_df = pd.DataFrame(all_rows)
    farmers_df.columns = farmers_df.columns.str.lower()
    farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.strip().str.lower()
    return farmers_df

def delete_existing_delivery_rpc(export_lot, exporter_name):
    export_lot = str(export_lot)
    exporter_name = str(exporter_name)
    try:
        supabase.rpc('delete_traceability_records', {
            'lot': export_lot,
            'exporter_param': exporter_name
        }).execute()
    except Exception as e:
        st.error(f"❌ RPC Delete Error: {e}")


def save_delivery_to_supabase(df):
    column_mapping = {
        'cooperative name': 'cooperative_name',
        'export lot n°/connaissement': 'export_lot',
        'date of purchase from cooperative': 'purchase_date',
        'certification': 'certification',
        'farmer_id': 'farmer_id',
        'net weight (kg)': 'net_weight_kg',
        'exporter': 'exporter'
    }
    df = df.rename(columns=column_mapping)
    required_columns = ['export_lot', 'exporter', 'farmer_id', 'net_weight_kg']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        st.error(f"{t('missing_columns')}: {', '.join(missing_columns)}")
        return False

    df_cleaned = df.copy()
    df_cleaned['farmer_id'] = df_cleaned['farmer_id'].str.strip().str.lower()
    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))
    # Najpierw zamień na string, żeby nie było błędów typu "float" -> np. nan
    df_cleaned['certification'] = df_cleaned['certification'].astype(str)

# Następnie wszystko, co wygląda na puste/N/A/nan, zamień na None
    df_cleaned['certification'] = df_cleaned['certification'].replace(
        ['N/A', 'n/a', 'na', 'NA', 'NaN', 'nan', '', 'None'], None
    )





    # ✅ Updated Excel date converter INSIDE this function
    def excel_date_to_date(excel_date):
        """Converts Excel dates (numbers or strings) to ISO 'YYYY-MM-DD'.
        If parsing fails, returns today's date."""
        today_str = datetime.today().strftime("%Y-%m-%d")

        if pd.isna(excel_date) or excel_date == "":
            return today_str

        # Excel serial (number)
        if isinstance(excel_date, (int, float)):
            try:
                return (
                    pd.to_datetime("1899-12-30") + pd.to_timedelta(excel_date, unit="D")
                ).strftime("%Y-%m-%d")
            except Exception:
                return today_str

        # datetime-like
        if isinstance(excel_date, (datetime, pd.Timestamp)):
            try:
                return pd.to_datetime(excel_date).strftime("%Y-%m-%d")
            except Exception:
                return today_str

        # strings: 18/09/2025, 18-09-2025, 18.09.2025, or serial as text
        if isinstance(excel_date, str):
            s = excel_date.strip()
            dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
            if pd.notna(dt):
                return dt.strftime("%Y-%m-%d")
            num = pd.to_numeric(s, errors="coerce")
            if pd.notna(num):
                dt = pd.to_datetime(num, unit="D", origin="1899-12-30", errors="coerce")
                if pd.notna(dt):
                    return dt.strftime("%Y-%m-%d")

        return today_str

    # ✅ same lines as before, now safe
    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].apply(excel_date_to_date)
    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].astype(str)

    data = df_cleaned.to_dict(orient="records")

    # Check for missing required fields
    required_fields = ['export_lot', 'exporter', 'farmer_id', 'net_weight_kg']
    missing_values = df_cleaned[required_fields].isnull().any(axis=1)

    if missing_values.any():
        st.error("❌ Some rows have missing values in required fields:")
        st.dataframe(df_cleaned[missing_values])
        return False

    try:
        with st.spinner(t("saving")):
            supabase.table("traceability").insert(data).execute()
        st.success(t("insert_success").format(len(data)))
        return True
    except Exception as e:
        st.error(f"{t('insert_error')}: {e}")
        return False

def upload_file_to_sharepoint(site_url, client_id, client_secret, folder_path, file_name, file_content):
    """
    Upload a file to SharePoint using Office365 library.
    If a file with the same name exists, appends (2), (3), etc.
    """
    try:
        # 1) Auth
        ctx = ClientContext(site_url).with_credentials(ClientCredential(client_id, client_secret))

        # 2) Load web + explicitly request ServerRelativeUrl
        web = ctx.web
        ctx.load(web, ["Title", "ServerRelativeUrl"])
        ctx.execute_query()

        # 3) Get base server-relative URL
        base = web.properties.get("ServerRelativeUrl")
        if not base:
            base = urlparse(site_url).path.rstrip("/") or "/"

        # 4) Build correct folder URL
        folder_url = f"{base.rstrip('/')}/{str(folder_path).lstrip('/')}"

        # 5) Ensure folder exists / is accessible
        target_folder = ctx.web.get_folder_by_server_relative_url(folder_url)
        ctx.load(target_folder, ["ServerRelativeUrl", "Name"])
        ctx.execute_query()

        # 6) Read bytes
        if hasattr(file_content, "getvalue"):
            data = file_content.getvalue()
        elif hasattr(file_content, "read"):
            try:
                file_content.seek(0)
            except Exception:
                pass
            data = file_content.read()
        elif isinstance(file_content, (bytes, bytearray)):
            data = file_content
        else:
            raise TypeError("file_content must be bytes, BytesIO, or a file-like object")

        # 7) Check for existing files and build a unique name
        unique_file_name = get_unique_sharepoint_filename(ctx, folder_url, file_name)

        # 8) Upload with unique name
        target_folder.upload_file(unique_file_name, data).execute_query()
        st.success(f"✅ Uploaded to SharePoint: {folder_url}/{unique_file_name}")
        return True

    except Exception as e:
        st.error(f"❌ SharePoint upload failed: {type(e).__name__}: {e}")
        return False


def get_unique_sharepoint_filename(ctx, folder_url, file_name):
    import os
    name_without_ext, ext = os.path.splitext(file_name)

    # Wyciąga prefix BEZ wartości MT
    # np. "LOT123_ExporterXYZ_CoopABC_50.0MT" → "LOT123_ExporterXYZ_CoopABC"
    identity_prefix = re.sub(r'_[\d.]+MT$', '', name_without_ext, flags=re.IGNORECASE)

    try:
        folder = ctx.web.get_folder_by_server_relative_url(folder_url)
        files = folder.files
        ctx.load(files, ["Name"])
        ctx.execute_query()
        existing_names = [f.properties["Name"] for f in files]
    except Exception as e:
        st.warning(f"⚠️ Could not list SharePoint files: {e}")
        return file_name

    # Liczy pliki z tym samym prefixem (ignorując MT i wersje)
    matching_count = 0
    for existing in existing_names:
        existing_no_ext, _ = os.path.splitext(existing)
        existing_clean = re.sub(r'\(\d+\)$', '', existing_no_ext).strip()  # usuń (2), (3)
        existing_prefix = re.sub(r'_[\d.]+MT$', '', existing_clean, flags=re.IGNORECASE)

        if existing_prefix.lower() == identity_prefix.lower():
            matching_count += 1

    if matching_count == 0:
        return file_name
    else:
        version = matching_count + 1
        return f"{name_without_ext}({version}){ext}"


def generate_pdf_confirmation(
    lot_numbers, exporter_name, farmer_count, total_kg, lot_kg_summary,
    logo_path, logo_cocoa, cooperative_names, uploaded_file_content,
    delivery_file_name, non_eudr_total_kg=0
):
    """
    Generate PDF and upload both PDF and Excel to SharePoint.
    Returns (filename, pdf_bytes) for download button.
    """
    import streamlit as st
    from fpdf import FPDF
    from datetime import datetime
    from io import BytesIO
    import re
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(200, 10, "Delivery Approval Certificate", ln=True, align="C")

    if logo_path:
        try:
            pdf.image(logo_path, x=10, y=20, w=40)
        except Exception as e:
            st.warning(f"Could not embed logo from {logo_path}: {e}")
    if logo_cocoa:
        try:
            pdf.image(logo_cocoa, x=(210 - 110) / 2, y=20, w=110)
        except Exception as e:
            st.warning(f"Could not embed logo from {logo_cocoa}: {e}")

    pdf.set_y(70)
    pdf.set_font("Arial", "", 12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.multi_cell(0, 10, f"Generated on: {now}")
    pdf.multi_cell(0, 10, f"Exporter: {exporter_name}")
    pdf.multi_cell(0, 10, f"Cooperatives: {', '.join(sorted(set(cooperative_names)))}")
    pdf.multi_cell(0, 10, f"Lots: {', '.join(str(l) for l in lot_numbers)}")
    pdf.multi_cell(0, 10, f"Total Farmers: {farmer_count}")
    pdf.multi_cell(0, 10, f"Total Net Weight: {round(total_kg / 1000, 2)} MT")

    if non_eudr_total_kg and non_eudr_total_kg > 0:
        pdf.multi_cell(
            0, 10,
            f"(Includes {round(non_eudr_total_kg/1000, 2)} MT marked as Non-EUDR - "
            f"excluded from DB & quota checks)"
        )

    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Lot Summary", ln=True)
    pdf.set_font("Arial", "", 12)
    for lot in lot_numbers:
        kg = lot_kg_summary.get(lot, 0)
        pdf.cell(0, 10, f"{lot}: {round(kg / 1000, 2)} MT", ln=True)

    pdf.ln(5)
    pdf.cell(0, 10, "Approved by CloudIA", ln=True)

    # Generate filename
    reference_number = lot_numbers[0] if len(lot_numbers) == 1 else "MULTI"
    reference_number = re.sub(r"[^\w\-]", "_", str(reference_number))
    today_str = datetime.now().strftime('%Y%m%d')
    exporter_clean = exporter_name.replace(" ", "").replace("/", "")[:20]
    total_volume_mt = round(total_kg / 1000, 2)
    filename = f"Approval_{reference_number}_{today_str}_{exporter_clean}_{total_volume_mt}MT.pdf"
    cooperative_clean = re.sub(r"[^\w\-]", "_", "_".join(sorted(set([c.strip() for c in cooperative_names])))[:30])
    excel_filename = f"{reference_number}_{exporter_clean}_{cooperative_clean}_{total_volume_mt}MT.xlsx"
    
    # Save PDF to bytes (don't save to disk)
    pdf_bytes = pdf.output(dest='S').encode('latin1')

    # --- SAVE TO DATABASE ---
    data = {
        "created_at": now,
        "lot_number": ", ".join(str(l) for l in lot_numbers),
        "exporter_name": exporter_name,
        "approved_by": "CloudIA",
        "file_name": filename
    }
    try:
        from supabase import create_client
        supabase = create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
        supabase.table("approvals").insert(data).execute()
    except Exception as e:
        st.error(f"❌ Error saving approval to database: {e}")

    # --- SHAREPOINT UPLOAD (matching COOP app pattern) ---
    try:
        # Check if sharepoint config exists in secrets
        if "sharepoint" not in st.secrets:
            st.warning("⚠️ SharePoint configuration not found in secrets. Skipping upload.")
            return filename, pdf_bytes
        
        sharepoint_config = st.secrets["sharepoint"]
        
        # Verify all required keys exist
        required_keys = ["site_url", "client_id", "client_secret", "library_name"]
        missing_keys = [key for key in required_keys if key not in sharepoint_config]
        if missing_keys:
            st.warning(f"⚠️ Missing SharePoint config keys: {', '.join(missing_keys)}. Skipping upload.")
            return filename, pdf_bytes
        
        site_url = sharepoint_config["site_url"]
        client_id = sharepoint_config["client_id"]
        client_secret = sharepoint_config["client_secret"]
        library_name = sharepoint_config["library_name"]


        # Upload Excel
        st.info("📤 Uploading Excel to SharePoint...")
        success_excel = upload_file_to_sharepoint(
            site_url=site_url,
            client_id=client_id,
            client_secret=client_secret,
            folder_path=library_name,
            file_name=excel_filename,
            file_content=uploaded_file_content
        )

        if success_excel:
            st.success("✅ Excel file uploaded to SharePoint successfully!")
        else:
            st.error("❌ Excel upload failed. Check SharePoint configuration and logs.")

    except Exception as e:
        st.error(f"❌ SharePoint upload error: {e}")
        import traceback
        st.code(traceback.format_exc())

    # Return filename and bytes for download button
    return filename, pdf_bytes

def load_quota_view():
    # ✅ Load ALL rows with pagination (same as load_all_farmers)
    all_rows = []
    page_size = 1000
    last_farmer_id = None
    
    while True:
        query = supabase.table("quota_view").select("*").limit(page_size).order("farmer_id")
        if last_farmer_id:
            query = query.gt("farmer_id", last_farmer_id)
        result = query.execute()
        rows = result.data
        if not rows:
            break
        all_rows.extend(rows)
        last_farmer_id = rows[-1]["farmer_id"]
    
    df = pd.DataFrame(all_rows)

    # If empty, return a typed empty frame so downstream code has expected columns
    if df.empty:
        expected = [
            "farmer_id",
            "max_quota_kg",
            "total_net_weight_kg",
            "quota_used_pct",
            "quota_status",
        ]
        return pd.DataFrame(columns=expected)

    # normalize headers
    df.columns = df.columns.str.strip().str.lower()

    # map common aliases → farmer_id
    alias_map = {
        "farmerid": "farmer_id",
        "farmer-id": "farmer_id",
        "farmer_id_": "farmer_id",
        "id_farmer": "farmer_id",
        "idfarmer": "farmer_id",
    }
    for k, v in alias_map.items():
        if k in df.columns and "farmer_id" not in df.columns:
            df = df.rename(columns={k: v})
            break

    # Ensure required columns exist (create empty if the view lacks them)
    for col in ["max_quota_kg", "total_net_weight_kg", "quota_used_pct", "quota_status"]:
        if col not in df.columns:
            df[col] = pd.Series(dtype="float64" if col != "quota_status" else "object")

    return df

# --- UI Layout ---
def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_1 = image_to_base64(LOGO_PATH)
logo_2 = image_to_base64(LOGO_COCOA)

st.markdown(f"""
    <h1 style='text-align: center; font-size: 60px; color: #1c2b4a; margin-top: 10px; margin-bottom: 10px; letter-spacing: 6px;'>EXPORT</h1>

    <div style="display: flex; justify-content: center; align-items: center; gap: 80px; margin-bottom: 30px;">
        <img src="data:image/png;base64,{logo_1}" alt="CloudIA" style="height: 140px;">
        <img src="data:image/png;base64,{logo_2}" alt="Cocoa Source" style="height: 180px;">
    </div>

    <h2 style='text-align: center; color: #1c2b4a; font-size: 30px;'>
        {t('title')}
    </h2>
""", unsafe_allow_html=True)



# --- Główna logika ---
st.markdown(f"""
<div style='text-align: center; padding: 20px; border-radius: 12px; background-color: #f4f7fa; border: 1px solid #dbe3ea; margin-top: 20px;'>
    <h3>{t('upload_title')}</h3>
    <p><em>{t('or')}</em></p>
</div>
""", unsafe_allow_html=True)


delivery_file = st.file_uploader(" ", type=["xlsx"], label_visibility="collapsed")
st.caption(t("file_format_caption"))

farmers_df = load_all_farmers()

if delivery_file:
    # --- read & normalize ----------------------------------------------------
    uploaded_excel_bytes = delivery_file.getvalue()
    uploaded_excel_file = delivery_file  # keep original file object
    uploaded_df = pd.read_excel(uploaded_excel_file)  # read once
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()

    if 'farmer_id' in uploaded_df.columns:
        uploaded_df['farmer_id'] = uploaded_df['farmer_id'].astype(str).str.strip().str.lower()

    # basic schema checks
    if 'exporter' not in uploaded_df.columns:
        st.error(t("missing_exporter_column"))
        st.stop()

    expected_columns = [
        'cooperative name', 'export lot n°/connaissement', 'date of purchase from cooperative',
        'certification', 'farmer_id', 'farm_id', 'net weight (kg)', 'exporter'
    ]
    missing_columns = [c for c in expected_columns if c not in uploaded_df.columns]
    if missing_columns:
        st.error(t("missing_columns").format(', '.join(missing_columns)))
        st.stop()

    # rename + fill
    uploaded_df.rename(columns={
        'export lot n°/connaissement': 'export_lot',
        'net weight (kg)': 'net_weight_kg',
        'date of purchase from cooperative': 'purchase_date'
    }, inplace=True)
    uploaded_df['purchase_date'] = uploaded_df['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))

    # de-dup
    #uploaded_df = uploaded_df.drop_duplicates(
    #    subset=['export_lot', 'exporter', 'farmer_id', 'net_weight_kg'],
    #    keep='last'
    #)

    # empty file guard
    if uploaded_df.empty:
        st.error("❌ The uploaded file is empty or contains no valid delivery records.")
        st.stop()

    # --- SPLIT: EUDR vs Non-EUDR --------------------------------------------
    uploaded_df['certification'] = uploaded_df['certification'].astype(str)
    non_eudr_mask = uploaded_df['certification'].str.contains(
        r'\bnon[-_\s]*eudr\b', flags=re.IGNORECASE, na=False
    )

    df_noneudr = uploaded_df[non_eudr_mask].copy()     # NIE zapisujemy do DB, NIE walidujemy
    df_eudr    = uploaded_df[~non_eudr_mask].copy()    # TYLKO to zapisujemy i walidujemy

    if not df_noneudr.empty:
        st.info(
            f"ℹ Excluding {len(df_noneudr)} Non-EUDR rows from database & quota checks. "
            f"They will still count toward lot totals and appear in the PDF."
        )

    # --- unknown farmers check: ONLY on EUDR rows ----------------------------
    unknown_farmers = []
    if not df_eudr.empty:
        unknown_farmers = df_eudr[
            ~df_eudr['farmer_id'].str.lower().isin(farmers_df['farmer_id'].str.lower())
        ]['farmer_id'].unique().tolist()

    if unknown_farmers:
        st.error(t("unknown_farmers_error"))
        st.write(list(unknown_farmers))
        st.stop()

    # --- exporter names used later -------------------------------------------
    # For DB + RPC operations use EUDR-only exporters
    exporter_names = df_eudr['exporter'].dropna().astype(str).str.strip().unique() if not df_eudr.empty else []

# --- Process each exporter separately ---
# --- PRE-CLEAN: delete existing traceability ONLY for EUDR rows ------------
    for exporter_name in exporter_names:
        exporter_df = df_eudr[df_eudr['exporter'].str.strip() == exporter_name].copy()
        lot_numbers = exporter_df['export_lot'].unique()
        for lot in lot_numbers:
            delete_existing_delivery_rpc(lot, exporter_name)

    # dalej: inserted_ok = ..., quota_df = ..., PDF...


# ... (wszystko przed tym zostaje bez zmian)

    inserted_ok = True
    if not df_eudr.empty:
        inserted_ok = save_delivery_to_supabase(df_eudr)

    if not inserted_ok:
        st.stop()
    # Diagnoza – sprawdź czy kolumna farmer_id istnieje
    # --- QUOTA: load & filter only by EUDR farmer_ids --------------------------
    quota_df = load_quota_view()

    if 'farmer_id' not in quota_df.columns:
        st.error(t("missing_farmer_id_column").format(list(quota_df.columns)))
        st.stop()

    if not df_eudr.empty:
        uploaded_ids = pd.Series(df_eudr['farmer_id']).astype(str).str.strip().str.lower()
        quota_df['farmer_id'] = quota_df['farmer_id'].astype(str).str.strip().str.lower()
        quota_df = quota_df[quota_df['farmer_id'].isin(uploaded_ids)]
    else:
        # brak EUDR – brak rekordów do sprawdzania
        quota_df = quota_df.iloc[0:0]

    quota_filtered = quota_df[quota_df['quota_status'].isin(['EXCEEDED', 'WARNING'])]

# --- WARNINGS table (EUDR only) --------------------------------------------
    if not quota_filtered.empty:
        st.write(t("quota_overview_title"))

        def highlight_status(val):
            if val == 'EXCEEDED':
                return 'background-color: #ffcccc'
            elif val == 'WARNING':
                return 'background-color: #fff3cd'
            return ''

        styled_quota = quota_filtered[[
            'farmer_id', 'max_quota_kg', 'total_net_weight_kg', 'quota_used_pct', 'quota_status'
        ]].style.applymap(highlight_status, subset=['quota_status']).format({
            'max_quota_kg': '{:.0f}',
            'total_net_weight_kg': '{:.0f}',
            'quota_used_pct': '{:.2f}'
        })

        st.write(styled_quota)
        st.warning(t("quota_warning_count").format(len(quota_filtered)))
    else:
        st.success(t("quota_ok"))


    all_ids_valid = len(unknown_farmers) == 0
    any_quota_exceeded = 'EXCEEDED' in quota_filtered['quota_status'].values
    lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()

    def check_lot_status(weight_in_kg):
        weight_in_mt = weight_in_kg / 1000
        if math.floor(weight_in_mt * 100) < 1900:
            return t("lot_too_low")
        return t("lot_within_range")


    lot_status = lot_totals.apply(check_lot_status)
    lot_status_ok = lot_status == t("lot_within_range")


    lot_status_info = pd.DataFrame({
        'export_lot': lot_totals.index,
        'total_net_weight_kg': lot_totals.values,
        'lot_status': lot_status
    })

    if not lot_status_ok.all():
        st.write(t("lot_status_out_of_range"))
        st.dataframe(lot_status_info[~lot_status_ok])

    def rollback_delivery_eudr(df_eudr_rows):
        """Usuwa z DB tylko rekordy EUDR z bieżącego wrzutu, po eksporterze i locie."""
        if df_eudr_rows.empty:
            st.error(t("rollback_error"))
            return
        for exporter_name in df_eudr_rows['exporter'].dropna().astype(str).str.strip().unique():
            sub_exp = df_eudr_rows[df_eudr_rows['exporter'].str.strip() == exporter_name]
            for lot in sub_exp['export_lot'].unique():
                delete_existing_delivery_rpc(lot, exporter_name)
        st.error(t("rollback_error"))

    
    final_lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()
    final_exporter_names = ", ".join(sorted(set(uploaded_df['exporter'].dropna().astype(str).str.strip())))
    total_kg = int(final_lot_totals.sum())
    non_eudr_total_kg = int(df_noneudr['net_weight_kg'].sum()) if not df_noneudr.empty else 0

    if all_ids_valid and not any_quota_exceeded and lot_status_ok.all():
        st.success(t("file_approved"))
        if st.button(t("generate_pdf")):
            total_kg = int(final_lot_totals.sum())
            
            # This now returns (filename, pdf_bytes) instead of just filename
            pdf_filename, pdf_bytes = generate_pdf_confirmation(
                lot_numbers=final_lot_totals.index.tolist(),
                exporter_name=final_exporter_names,
                farmer_count=df_eudr['farmer_id'].nunique() if not df_eudr.empty else 0,
                total_kg=total_kg,
                lot_kg_summary=final_lot_totals.to_dict(),
                cooperative_names=uploaded_df['cooperative name'].dropna().unique().tolist(),
                logo_path=LOGO_PATH,
                logo_cocoa=LOGO_COCOA,
                uploaded_file_content=uploaded_excel_bytes,
                delivery_file_name=uploaded_excel_file.name,
                non_eudr_total_kg=non_eudr_total_kg,
            )
            
            # Use the bytes directly for download (no file I/O)
            st.download_button(
                t("download_pdf"), 
                data=pdf_bytes,  # Use the bytes directly
                file_name=pdf_filename, 
                mime="application/pdf"
            )
    else:
        rollback_delivery_eudr(df_eudr)