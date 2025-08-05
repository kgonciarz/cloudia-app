import pandas as pd
from supabase import create_client, Client
import numpy as np

# === Supabase connection ===
url = "https://hmrftqougofiigklkave.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhtcmZ0cW91Z29maWlna2xrYXZlIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NDcyMzc0MCwiZXhwIjoyMDYwMjk5NzQwfQ.v1nKYSogiel64zj4CHgfN0YzCtniFDXwjJxtUl4hEEo"
supabase: Client = create_client(url, key)

# === Ścieżka do Excela ===
excel_path = r"C:\Users\Klaudia Gonciarz\OneDrive - Cocoasource SA\Bureau\KUKUOM.xlsx"

# === Wczytaj dane ===
df = pd.read_excel(excel_path)

# Usuń wiersze bez farmer_id (ważne!)
df = df.dropna(subset=['farmer_id'])

# Zamień NaN na None (bo Supabase nie przyjmuje NaN)
df = df.replace({np.nan: None})

# === Wstaw/aktualizuj dane ===
for index, row in df.iterrows():
    record = row.to_dict()

    if not record:
        print(f"Pusty rekord w wierszu {index}, pominięto.")
        continue

    try:
        response = supabase.table("farmers").upsert(record, on_conflict=["farmer_id"]).execute()

        if response.data is None:
            print(f"❌ Błąd przy farmer_id {record.get('farmer_id')}, response: {response}")
        else:
            print(f"✅ Zapisano farmer_id {record.get('farmer_id')}")
    except Exception as e:
        print(f"❌ WYJĄTEK przy farmer_id {record.get('farmer_id')}: {e}")
