import requests
import pandas as pd
from io import StringIO

LOCATION_CODE = "werkendam.nieuwemerwede"
VALUES_WINDOW = "-48,48"  # laatste 48 uur tot 48 uur vooruit (exact zoals je link)

chart_url = "https://waterinfo.rws.nl/api/chart/get"
params = {
    "mapType": "waterhoogte",
    "locationCodes": LOCATION_CODE,
    "values": VALUES_WINDOW
}

r = requests.get(chart_url, params=params, timeout=30)
r.raise_for_status()

text = r.text.strip()
if not text:
    raise RuntimeError("Lege response van chart/get")

# CSV inlezen met ; als delimiter en NL headers
df = pd.read_csv(StringIO(text), sep=';')

# Kolomnamen zoals ze doorgaans heten in deze CSV:
# - "Datum" (bijv. 10-03-2026)
# - "Tijd (NL tijd)" (bijv. 15:10)
# - "Locatie"
# - "Waterhoogte in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"
# - "Waterhoogte verwachting in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"
col_actual = "Waterhoogte in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"
col_future = "Waterhoogte verwachting in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"


# omzet naar floats
df["actual_cm"] = pd.to_numeric(df[col_actual].astype(str).str.replace(" cm",""), errors="coerce")
df["future_cm"] = pd.to_numeric(df[col_future].astype(str).str.replace(" cm",""), errors="coerce")


# Soms staat er ' cm' of lege cellen – even netjes opschonen
df["waterhoogte_cm"] = df["actual_cm"].fillna(df["future_cm"])

# Alleen rijen met daadwerkelijke meetwaarde
df_meet = df.dropna(subset=["waterhoogte_cm"]).copy()

if df_meet.empty:
    raise RuntimeError("Geen meetwaarden gevonden in de CSV (allemaal leeg?).")

# Hoogste waarde en bijbehorende datum/tijd
idxmax = df_meet["waterhoogte_cm"].idxmax()
max_row = df_meet.loc[idxmax]

# Handige samengestelde timestamp (NL datum en tijd uit de CSV)
when = f"{max_row['Datum']} {max_row['Tijd (NL tijd)']}"

print(f"📍 Locatie: {max_row.get('Locatie', LOCATION_CODE)}")
print(f"🧭 Venster: values={VALUES_WINDOW} uur (t.o.v. nu)")
print(f"🌊 Hoogste waterhoogte (gemeten): {int(round(max_row['waterhoogte_cm']))} cm")
print(f"🕒 Moment (NL tijd volgens CSV): {when}")

