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
            "English": "☁️ CloudIA – Farmer Quota Verification System",
            "Français": "☁️ CloudIA – Système de Vérification des Quotas"
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
            "English": "⚠️ {} farmers in the uploaded file have quota warnings or exceeded limits.",
            "Français": "⚠️ {} producteurs du fichier ont des avertissements de quota ou ont dépassé les limites."
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
LOGO_COCOA = "cocoasourcelogo.jpg"

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

def delete_existing_delivery_rpc(export_lot, exporter_name, farmer_ids):
    export_lot = str(export_lot)
    exporter_name = str(exporter_name)
    if hasattr(farmer_ids, 'tolist'):
        farmer_ids = farmer_ids.tolist()
    farmer_ids = [str(farmer_id) for farmer_id in farmer_ids]
    try:
        supabase.rpc('delete_traceability_records', {
            'lot': export_lot,
            'exporter_param': exporter_name,
            'farmer_ids': farmer_ids
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




    def excel_date_to_date(excel_date):
        if isinstance(excel_date, (int, float)):
            return (pd.to_datetime('1899-12-30') + pd.to_timedelta(excel_date, unit='D')).strftime('%Y-%m-%d')
        return excel_date

    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].apply(excel_date_to_date)
    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].astype(str)
    data = df_cleaned.to_dict(orient="records")

    # Sprawdź, czy są puste wymagane pola w jakimkolwiek wierszu
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
def refresh_quota_view():
    try:
        supabase.rpc("refresh_quota_view").execute()
        print("✅ quota_view successfully refreshed.")
    except Exception as e:
        print("❌ Failed to refresh quota_view:", e)

refresh_quota_view()

def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, lot_kg_summary, logo_path, logo_cocoa, cooperative_names):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(200, 10, "Delivery Approval Certificate", ln=True, align="C")

    if logo_path:
        pdf.image(logo_path, x=10, y=20, w=40)
    if logo_cocoa:
        pdf.image(logo_cocoa, x=(210 - 110) / 2, y=20, w=110)

    pdf.set_y(70)
    pdf.set_font("Arial", "", 12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.multi_cell(0, 10, f"Generated on: {now}")
    pdf.multi_cell(0, 10, f"Exporter: {exporter_name}")
    pdf.multi_cell(0, 10, f"Cooperatives: {', '.join(sorted(set(cooperative_names)))}")
    pdf.multi_cell(0, 10, f"Lots: {', '.join(str(l) for l in lot_numbers)}")
    pdf.multi_cell(0, 10, f"Total Farmers: {farmer_count}")
    pdf.multi_cell(0, 10, f"Total Net Weight: {round(total_kg / 1000, 2)} MT")

    pdf.ln(5)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Lot Summary", ln=True)
    pdf.set_font("Arial", "", 12)
    for lot, kg in lot_kg_summary.items():
        pdf.cell(0, 10, f"{lot}: {round(kg / 1000, 2)} MT", ln=True)

    pdf.ln(5)
    pdf.cell(0, 10, "Approved by CloudIA", ln=True)

    reference_number = lot_numbers[0] if len(lot_numbers) == 1 else "MULTI"
    reference_number = re.sub(r"[^\w\-]", "_", str(reference_number))
    today_str = datetime.now().strftime('%Y%m%d')
    exporter_clean = exporter_name.replace(" ", "_").replace("/", "_")[:20]
    total_volume_mt = round(total_kg / 1000, 2)

    filename = f"Approval_{reference_number}_{today_str}_{exporter_clean}_{total_volume_mt}MT.pdf"
    pdf.output(filename)

    # --- ZAPISZ DO TABELI approvals ---
    data = {
        "created_at": now,
        "lot_number": ", ".join(str(l) for l in lot_numbers),
        "exporter_name": exporter_name,
        "approved_by": "CloudIA",
        "file_name": filename
    }
    try:
        supabase.table("approvals").insert(data).execute()
    except Exception as e:
        st.error(f"{t('approval_save_error')}: {e}")

    return filename


def load_quota_view():
    result = supabase.table("quota_view").select("*").execute()
    return pd.DataFrame(result.data)

# --- UI Layout ---
def image_to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

logo_1 = image_to_base64(LOGO_PATH)      # np. cloudia_logo.png
logo_2 = image_to_base64(LOGO_COCOA)     # np. cocoasourcelogo.jpg

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


delivery_file = st.file_uploader("", type=["xlsx"], label_visibility="collapsed")
st.caption(t("file_format_caption"))

farmers_df = load_all_farmers()

if delivery_file:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()
    uploaded_df['farmer_id'] = uploaded_df['farmer_id'].astype(str).str.strip().str.lower()

    if 'exporter' not in uploaded_df.columns:
        st.error(t("missing_exporter_column"))
        st.stop()

    exporter_names = uploaded_df['exporter'].dropna().astype(str).str.strip().unique()

    expected_columns = ['cooperative name', 'export lot n°/connaissement', 'date of purchase from cooperative',
                        'certification', 'farmer_id', 'farm_id', 'net weight (kg)', 'exporter']
    missing_columns = [col for col in expected_columns if col not in uploaded_df.columns]
    if missing_columns:
        st.error(t("missing_columns").format(', '.join(missing_columns)))
        st.stop()

    uploaded_df.rename(columns={
        'export lot n°/connaissement': 'export_lot',
        'net weight (kg)': 'net_weight_kg',
        'date of purchase from cooperative': 'purchase_date'
    }, inplace=True)

    uploaded_df['purchase_date'] = uploaded_df['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))

    uploaded_df = uploaded_df.drop_duplicates(subset=['export_lot', 'exporter', 'farmer_id', 'net_weight_kg'], keep='last')

    # ZABEZPIECZENIE: blokuj puste pliki
    if uploaded_df.empty:
        st.error("❌ The uploaded file is empty or contains no valid delivery records.")
        st.stop()


    unknown_farmers = uploaded_df[
        ~uploaded_df['farmer_id'].str.lower().isin(farmers_df['farmer_id'].str.lower())
    ]['farmer_id'].unique()

    if unknown_farmers.size > 0:
        st.error(t("unknown_farmers_error"))
        st.write(list(unknown_farmers))
        st.stop()


# --- Process each exporter separately ---
    for exporter_name in exporter_names:
        exporter_df = uploaded_df[uploaded_df['exporter'].str.strip() == exporter_name]
        exporter_df['exporter'] = exporter_name  # re-assign clean name

        lot_numbers = exporter_df['export_lot'].unique()
        for lot in lot_numbers:
            farmer_ids_for_lot = exporter_df[exporter_df['export_lot'] == lot]['farmer_id'].unique().tolist()
            delete_existing_delivery_rpc(lot, exporter_name, farmer_ids_for_lot)

    # dalej: inserted_ok = ..., quota_df = ..., PDF...


# ... (wszystko przed tym zostaje bez zmian)

    inserted_ok = save_delivery_to_supabase(uploaded_df)
    if not inserted_ok:
        st.stop()

    time.sleep(1)  # daj czas na propagację danych
    quota_df = load_quota_view()

    # Diagnoza – sprawdź czy kolumna farmer_id istnieje
    if 'farmer_id' not in quota_df.columns:
        st.error(t("missing_farmer_id_column").format(list(quota_df.columns)))
        st.stop()

    # Czyszczenie i filtrowanie
    uploaded_ids = pd.Series(uploaded_df['farmer_id']).astype(str).str.strip().str.lower()
    quota_df['farmer_id'] = quota_df['farmer_id'].astype(str).str.strip().str.lower()
    quota_df = quota_df[quota_df['farmer_id'].isin(uploaded_ids)]

    quota_filtered = quota_df[quota_df['quota_status'].isin(['EXCEEDED', 'WARNING'])]


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

        st.dataframe(styled_quota, use_container_width=True)
        st.warning(t("quota_warning_count").format(len(quota_filtered)))
    else:
        st.success(t("quota_ok"))

    all_ids_valid = len(unknown_farmers) == 0
    any_quota_exceeded = 'EXCEEDED' in quota_filtered['quota_status'].values
    lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()

    def check_lot_status(weight_in_kg):
            weight_in_mt = weight_in_kg / 1000
            if weight_in_mt < 21:
                return t("lot_too_low")
            else:
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

    def rollback_delivery(uploaded_df):
        lot_numbers = uploaded_df['export_lot'].unique()
        exporter_name = uploaded_df['exporter'].iloc[0]
        for lot in lot_numbers:
            farmer_ids_for_lot = uploaded_df[uploaded_df['export_lot'] == lot]['farmer_id'].unique().tolist()
            delete_existing_delivery_rpc(lot, exporter_name, farmer_ids_for_lot)
        st.error(t("rollback_error"))
    
    final_lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()
    final_exporter_names = ", ".join(sorted(set(uploaded_df['exporter'].dropna().astype(str).str.strip())))
    total_kg = int(final_lot_totals.sum())

    if all_ids_valid and not any_quota_exceeded and lot_status_ok.all():
        st.success(t("file_approved"))
        if st.button(t("generate_pdf")):
            total_kg = int(final_lot_totals.sum())
            pdf_file = generate_pdf_confirmation(
                lot_numbers=final_lot_totals.index.tolist(),
                exporter_name=final_exporter_names,
                farmer_count=uploaded_df['farmer_id'].nunique(),
                total_kg=total_kg,
                lot_kg_summary=final_lot_totals.to_dict(),
                cooperative_names=uploaded_df['cooperative name'].dropna().unique().tolist(),
                logo_path=LOGO_PATH,
                logo_cocoa=LOGO_COCOA
            )
            with open(pdf_file, "rb") as f:
                st.download_button(t("download_pdf"), data=f, file_name=pdf_file, mime="application/pdf")
    else:
        rollback_delivery(uploaded_df)

