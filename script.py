import os
import requests
import pandas as pd
from io import StringIO
from twilio.rest import Client

# ============================================================
# Instelbare parameters (simpel & centraal)
# ============================================================
LOCATION_CODES = [
    "werkendam.nieuwemerwede",
    "dordrecht.oudemaas.benedenmerwede",
]

# Nette labels voor in het bericht (optioneel)
LOCATION_LABELS = {
    "werkendam.nieuwemerwede": "Werkendam – Nieuwe Merwede",
    "dordrecht.oudemaas.benedenmerwede": "Dordrecht – Oude Maas/Beneden Merwede",
}

# Globale threshold (voor alle locaties)
THRESHOLD_CM = int(os.getenv("THRESHOLD_CM", "75"))

# Meerdere ontvangers mogelijk (komma-gescheiden via env of hieronder als list)
SEND_TO_NUMBERS = [
    # voorbeeld: zet hier je nummers neer
    "whatsapp:+31649549726",
    "whatsapp:+31629227763",
]
_env_to = os.getenv("SEND_TO_NUMBERS")
if _env_to:
    SEND_TO_NUMBERS = [x.strip() for x in _env_to.split(",") if x.strip()]

# Window voor data (laatste 48 uur tot 48 uur vooruit)
VALUES_WINDOW = "-48,48"

# ============================================================
# Constanten
# ============================================================
CHART_URL = "https://waterinfo.rws.nl/api/chart/get"

COL_ACTUAL = "Waterhoogte in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"
COL_FUTURE = "Waterhoogte verwachting in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"

# ============================================================
# Functies
# ============================================================

def fetch_max_waterhoogte(location_code: str) -> dict:
    """Haalt CSV-data op en geeft de hoogste waterhoogte (cm) en tijd terug."""
    params = {
        "mapType": "waterhoogte",
        "values": VALUES_WINDOW,
        "locationCodes": location_code,
    }

    text = requests.get(CHART_URL, params=params).text
    df = pd.read_csv(StringIO(text), sep=';')

    def to_num(s):
        return (
            s.astype(str)
             .str.replace(" cm", "", regex=False)
             .str.replace(",", ".", regex=False)
             .str.strip()
             .astype(float)
        )

    df["waterhoogte_cm"] = to_num(df[COL_FUTURE])

    max_row = df.loc[df["waterhoogte_cm"].idxmax()]

    return {
        "location_code": location_code,
        "label": LOCATION_LABELS.get(location_code, location_code),
        "locatie_csv": max_row.get("Locatie", location_code),
        "max_cm": float(max_row["waterhoogte_cm"]),
        "when": f"{max_row.get('Datum', '')} {max_row.get('Tijd (NL tijd)', '')}".strip(),
    }


def init_twilio():
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN"),
    )
    from_whatsapp = os.getenv("TWILIO_FROM_WHATSAPP", "whatsapp:+14155238886")
    return client, from_whatsapp


def send_alert(client, from_whatsapp, to_whatsapp, body):
    return client.messages.create(body=body, from_=from_whatsapp, to=to_whatsapp).sid


# ============================================================
# Main
# ============================================================

def main():
    # 1) Ophalen & tonen
    results = [fetch_max_waterhoogte(code) for code in LOCATION_CODES]
    for r in results:
        print(f"📍 {r['label']}: {int(round(r['max_cm']))} cm om {r['when']}")

    # 2) Alerts sturen (globale threshold + meerdere ontvangers)
    client, from_whatsapp = init_twilio()

    for r in results:
        max_value = int(round(r["max_cm"]))
        if max_value > THRESHOLD_CM:
            body = (
                "⚠️ WAARSCHUWING\n"
                f"Waterhoogte: {max_value} cm (drempel {THRESHOLD_CM} cm)\n"
                f"Tijd (NL tijd): {r['when']}\n"
                f"Locatie: {r['locatie_csv']} ({r['label']})\n\n"
                "(Automatische melding)"
            )
            for to in SEND_TO_NUMBERS:
                sid = send_alert(client, from_whatsapp, to, body)
                print(f"📲 Melding verstuurd naar {to} ({r['label']}). SID: {sid}")
        else:
            print(f"✅ {r['label']}: {max_value} cm ≤ {THRESHOLD_CM} cm — geen melding.")

    # 3) Samenvatting
    print("\n✅ Samenvatting:")
    for r in results:
        print(f"- {r['label']}: {int(round(r['max_cm']))} cm op {r['when']}")


if __name__ == "__main__":
    main()
