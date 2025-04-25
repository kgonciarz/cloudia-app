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

#def clean_farmer_id(val):
    #if pd.isnull(val) or val is None:
      #  return ""
   # val = str(val)  # Konwersja zawsze
    # Usuwamy tylko naprawdę niewidoczne śmieci
    #val = re.sub(r"[\s\u00a0\u200b\ufeff\u202f\u2060]+", "", val)
    #return val.strip().lower()


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
        last_farmer_id = rows[-1]["farmer_id"]  # ostatni ID

    farmers_df = pd.DataFrame(all_rows)
    farmers_df.columns = farmers_df.columns.str.lower()
    farmers_df['farmer_id'] = farmers_df['farmer_id'].astype(str).str.strip().str.lower()

    return farmers_df



def delete_existing_delivery(lot_number, exporter_name):
    supabase.table("traceability").delete().match({
        "export_lot": lot_number,
        "exporter": exporter_name
    }).execute()



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
        st.error(f"Missing required columns: {', '.join(missing_columns)}")
        return

    df_cleaned = df.copy()
    df_cleaned['farmer_id'] = df_cleaned['farmer_id'].str.strip().str.lower()
    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].fillna(datetime.today().strftime('%Y-%m-%d'))

    def excel_date_to_date(excel_date):
        if isinstance(excel_date, (int, float)):
            return (pd.to_datetime('1899-12-30') + pd.to_timedelta(excel_date, unit='D')).strftime('%Y-%m-%d')
        return excel_date

    df_cleaned['purchase_date'] = df_cleaned['purchase_date'].apply(excel_date_to_date)

    # Pobierz istniejące rekordy z Supabase
    existing_records = supabase.table("traceability").select("export_lot", "exporter", "farmer_id").execute().data
    existing_records_df = pd.DataFrame(existing_records)

    if not existing_records_df.empty:
        # Upewnij się, że potrzebne kolumny istnieją
        for col in ["export_lot", "exporter", "farmer_id"]:
            if col not in existing_records_df.columns:
                existing_records_df[col] = None

        # Czyszczenie i unifikacja formatowania
        for col in ["export_lot", "exporter", "farmer_id"]:
            existing_records_df[col] = existing_records_df[col].astype(str).str.strip().str.lower()
            df_cleaned[col] = df_cleaned[col].astype(str).str.strip().str.lower()

        # Usunięcie rekordów, które już istnieją w bazie
        merged = df_cleaned.merge(
            existing_records_df,
            on=["export_lot", "exporter", "farmer_id"],
            how="left",
            indicator=True
        )
        df_cleaned = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])

    if df_cleaned.empty:
        st.info("ℹ️ No new deliveries to insert. All records already exist.")
        return

    # Zapisz do Supabase
    data = df_cleaned.to_dict(orient="records")
    
    try:
        supabase.table("traceability").insert(data).execute()
        st.success(f"✅ Data successfully inserted! {len(data)} new records added.")
    except Exception as e:
        st.error(f"❌ Error while inserting into traceability table: {e}")
        print(f"Error details: {e}")





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

def generate_pdf_confirmation(lot_numbers, exporter_name, farmer_count, total_kg, lot_kg_summary, logo_path, logo_cocoa):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 14)
    pdf.cell(200, 10, "Delivery Approval Certificate", ln=True, align="C")

    # Logos
    if logo_path:
        pdf.image(logo_path, x=10, y=20, w=40)
    if logo_cocoa:
        pdf.image(logo_cocoa, x=(210 - 110) / 2, y=20, w=110)

    # Metadata section
    pdf.set_y(70)
    pdf.set_font("Arial", "", 12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    pdf.multi_cell(0, 10, f"Generated on: {now}")
    pdf.multi_cell(0, 10, f"Exporter: {exporter_name}")
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

    filename = f"approval_GFC_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    pdf.output(filename)

    # Save to DB
    save_approval_to_db(
        lot_numbers=lot_numbers,
        exporter_name=exporter_name,
        file_name=filename
    )

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

farmers_df = load_all_farmers()



if delivery_file:
    uploaded_df = pd.read_excel(delivery_file)
    uploaded_df.columns = uploaded_df.columns.str.strip().str.lower()

    # 🔧 Dodaj bezpieczne czyszczenie farmer_id
    if 'farmer_id' in uploaded_df.columns:
        uploaded_df['farmer_id'] = uploaded_df['farmer_id'].astype(str).str.strip().str.lower()



    if 'exporter' not in uploaded_df.columns:
        st.error("Missing 'exporter' column in the Excel file.")
        st.stop()

    exporter_name = uploaded_df['exporter'].dropna().astype(str).iloc[0]

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
    uploaded_df = uploaded_df.drop_duplicates(subset=['export_lot', 'exporter', 'farmer_id', 'net_weight_kg'], keep='last')

    unknown_farmers = uploaded_df[~uploaded_df['farmer_id'].isin(farmers_df['farmer_id'])]['farmer_id'].unique()


    #for db_id in farmers_df['farmer_id']:


    if unknown_farmers.size > 0:
        st.error("The following farmers are NOT in the database:")
        st.write(list(unknown_farmers))
        st.stop()

    for lot in uploaded_df['export_lot'].unique():
        delete_existing_delivery(lot, exporter_name)
    save_delivery_to_supabase(uploaded_df)

    

    #@st.cache_data
    def load_quota_view():
        result = supabase.table("quota_view").select("*").execute()
        return pd.DataFrame(result.data)

    quota_df = load_quota_view()

    exceeded_df = quota_df[quota_df['quota_status'] == 'EXCEEDED']

    #if not exceeded_df.empty:
     #   st.warning("These farmers have exceeded their quota:")
      #  st.dataframe(exceeded_df[['farmer_id', 'total_net_weight_kg', 'max_quota_kg', 'quota_used_pct']])

    st.write("### Quota Overview (Only Warnings and Exceeded)")
    quota_filtered = quota_df[quota_df['quota_status'].isin(['EXCEEDED', 'WARNING'])]

    def highlight_status(val):
        if val == 'EXCEEDED':
            return 'background-color: #ffcccc'  # czerwony
        elif val == 'WARNING':
            return 'background-color: #fff3cd'  # żółty
        return ''

    styled_quota = quota_filtered[['farmer_id', 'max_quota_kg', 'total_net_weight_kg', 'quota_used_pct', 'quota_status']]\
        .style.applymap(highlight_status, subset=['quota_status'])

    st.dataframe(styled_quota, use_container_width=True)





    all_ids_valid = len(unknown_farmers) == 0
    any_quota_exceeded = not exceeded_df.empty

    lot_totals = uploaded_df.groupby('export_lot')['net_weight_kg'].sum()

    if all_ids_valid and not any_quota_exceeded:
        st.success("File approved...")

    
    # Function to check lot weight status
    def check_lot_status(weight_in_kg):
        weight_in_mt = weight_in_kg / 1000  # Convert to metric tons (MT)
        if weight_in_mt < 21:
            return "Too low"
        elif weight_in_mt > 29:
            return "Too high"
        else:
            return "Within range"
    
    # Apply lot weight status check
    lot_status = lot_totals.apply(check_lot_status)
    
    # Check if all lots are within range (between 21 and 29 MT)
    lot_status_ok = lot_status == "Within range"
    
    # Display lot status validation information
    lot_status_info = pd.DataFrame({
        'export_lot': lot_totals.index,
        'total_net_weight_kg': lot_totals.values,
        'lot_status': lot_status
    })
    lot_status_outside_range = lot_status_info[~lot_status_ok]
    # Display lot status validation information
    if not lot_status_outside_range.empty:
        st.write("### Lot Status Overview - Out of Range")
        st.dataframe(lot_status_outside_range)


    st.write("all_ids_valid:", all_ids_valid)
    st.write("any_quota_exceeded:", any_quota_exceeded)
    st.write("lot_status_ok:", lot_status_ok.all())


    if all(lot_status_ok):
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
    else:
    # Only display this if some lots are not within range (to avoid duplication)
        if lot_status_outside_range.empty:
            st.success("All lots are within the allowed range!")
