import requests
import pandas as pd
from io import StringIO
import os
from twilio.rest import Client

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


max_value = int(round(max_row["waterhoogte_cm"]))

if max_value > 75:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars.")

    client = Client(account_sid, auth_token)

    body = (
        f"⚠️ WAARSCHUWING\n"
        f"Waterhoogte: {max_value} cm\n"
        f"Moment (NL tijd, CSV): {when}\n"
        f"Locatie: {max_row.get('Locatie', LOCATION_CODE)}\n\n"
        f"(Automatische melding)"
    )

    try:
        message = client.messages.create(
            body=body,
            from_="whatsapp:+14155238886",  # Twilio WhatsApp Sandbox
            to="whatsapp:+31629227763" 
        )
        print("📲 WhatsApp-melding verzonden. SID:", message.sid)
    except Exception as e:
        print("❌ WhatsApp verzenden mislukt:", e)
        raise
else:
    print("✅ Waterhoogte veilig — geen melding.")
