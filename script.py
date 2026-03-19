import os
import requests
import pandas as pd
from io import StringIO
from twilio.rest import Client

# === Instellingen ===
LOCATION_CODES = [
    "werkendam.nieuwemerwede",
    "dordrecht.oudemaas.benedenmerwede",
]
VALUES_WINDOW = "-48,48"  # laatste 48 uur tot 48 uur vooruit

# Per-locatie configuratie voor melding
ALERT_CONFIG = {
    "werkendam.nieuwemerwede": {
        "threshold_cm": 75,                     # drempel in cm
        "to": "whatsapp:+31649549726",         # ontvanger
        "label": "Werkendam – Nieuwe Merwede",  # nette naam in body
    },
    "dordrecht.oudemaas.benedenmerwede": {
        "threshold_cm": 75,
        "to": "whatsapp:+31649549726",
        "label": "Dordrecht – Oude Maas/Beneden Merwede",
    },
}

CHART_URL = "https://waterinfo.rws.nl/api/chart/get"
PARAMS_BASE = {
    "mapType": "waterhoogte",
    "values": VALUES_WINDOW
}

# Kolomnamen zoals RWS ze typisch levert
COL_DATE = "Datum"
COL_TIME = "Tijd (NL tijd)"
COL_LOCATION = "Locatie"
COL_ACTUAL = "Waterhoogte in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"
COL_FUTURE = "Waterhoogte verwachting in Oppervlaktewater t.o.v. Normaal Amsterdams Peil in cm"


def fetch_max_waterhoogte(location_code: str) -> dict:
    """Haalt CSV op voor de locatie, berekent hoogste waterhoogte (gemeten of verwachting als gemeten ontbreekt).
    Retourneert dict met details of een dict met 'error' bij mislukking.
    """
    params = {**PARAMS_BASE, "locationCodes": location_code}
    try:
        r = requests.get(CHART_URL, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return {"location_code": location_code, "error": f"HTTP-fout: {e}"}

    text = r.text.strip()
    if not text:
        return {"location_code": location_code, "error": "Lege response van chart/get"}

    try:
        df = pd.read_csv(StringIO(text), sep=';')
    except Exception as e:
        return {"location_code": location_code, "error": f"CSV-parsing mislukt: {e}"}

    # naar numeriek: strip eventuele ' cm' en whitespace
    def to_num(series):
        return pd.to_numeric(series.astype(str)
                             .str.replace(" cm", "", regex=False)
                             .str.replace(",", ".", regex=False)  # decimaal met komma
                             .str.strip(),
                             errors="coerce")

    df["actual_cm"] = to_num(df[COL_ACTUAL]) if COL_ACTUAL in df.columns else pd.NA
    df["future_cm"] = to_num(df[COL_FUTURE]) if COL_FUTURE in df.columns else pd.NA

    # combineer: pak gemeten waar beschikbaar, anders verwachting
    df["waterhoogte_cm"] = df["actual_cm"]
    df.loc[df["waterhoogte_cm"].isna(), "waterhoogte_cm"] = df["future_cm"]

    df_meet = df.dropna(subset=["waterhoogte_cm"]).copy()
    if df_meet.empty:
        return {"location_code": location_code, "error": "Geen meetwaarden (alles leeg?)"}

    idxmax = df_meet["waterhoogte_cm"].idxmax()
    max_row = df_meet.loc[idxmax]

    # timestamp
    datum = max_row[COL_DATE] if COL_DATE in df_meet.columns else ""
    tijd = max_row[COL_TIME] if COL_TIME in df_meet.columns else ""
    when = f"{datum} {tijd}".strip()

    # locatie (uit CSV, anders fallback naar code)
    locatie = max_row[COL_LOCATION] if COL_LOCATION in df_meet.columns else location_code

    return {
        "location_code": location_code,
        "locatie": locatie,
        "values_window": VALUES_WINDOW,
        "max_cm": float(max_row["waterhoogte_cm"]),
        "when": when
    }


def init_twilio():
    """Initialiseer Twilio client 1x en geef from/to terug."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise RuntimeError("Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN env vars.")

    client = Client(account_sid, auth_token)

    # Afzender: uit env of fallback naar WhatsApp Sandbox
    from_whatsapp = os.getenv("TWILIO_FROM_WHATSAPP", "whatsapp:+14155238886")
    return client, from_whatsapp


def send_alert(client: Client, from_whatsapp: str, to_whatsapp: str, body: str):
    """Stuur WhatsApp bericht via Twilio."""
    message = client.messages.create(
        body=body,
        from_=from_whatsapp,
        to=to_whatsapp,
    )
    return message.sid


def main():
    resultaten = []
    for code in LOCATION_CODES:
        res = fetch_max_waterhoogte(code)
        resultaten.append(res)
        if "error" in res:
            print(f"⚠️  {code}: {res['error']}")
        else:
            print(f"📍 Locatie: {res['locatie']} ({code})")
            print(f"🧭 Venster: values={res['values_window']} uur (t.o.v. nu)")
            print(f"🌊 Hoogste waterhoogte: {int(round(res['max_cm']))} cm")
            print(f"🕒 Moment (NL tijd volgens CSV): {res['when']}")
            print("-" * 60)

    # === Nieuw: alerts per locatie ===
    try:
        client, from_whatsapp = init_twilio()
    except Exception as e:
        print("❌ Twilio initialisatie mislukt:", e)
        client = None
        from_whatsapp = None

    for res in resultaten:
        if "error" in res:
            continue

        code = res["location_code"]
        max_value = int(round(res["max_cm"]))
        when = res["when"]
        locatie_uit_csv = res.get("locatie", code)

        # Config ophalen (threshold en ontvanger)
        cfg = ALERT_CONFIG.get(code)
        if not cfg:
            # Geen config -> geen melding
            print(f"ℹ️  Geen alertconfig voor {code}; melding overgeslagen.")
            continue

        threshold = int(cfg.get("threshold_cm", 75))
        to_whatsapp = cfg["to"]
        nette_label = cfg.get("label", code)

        if max_value > threshold:
            if not client:
                print(f"❌ Geen Twilio client beschikbaar; kan melding voor {nette_label} niet sturen.")
                continue

            body = (
                "⚠️ WAARSCHUWING\n"
                f"Waterhoogte: {max_value} cm\n"
                f"Moment (NL tijd, CSV): {when}\n"
                f"Locatie: {locatie_uit_csv} ({nette_label})\n\n"
                "(Automatische melding)"
            )
            try:
                sid = send_alert(client, from_whatsapp, to_whatsapp, body)
                print(f"📲 WhatsApp-melding verzonden voor {nette_label}. SID: {sid}")
            except Exception as e:
                print(f"❌ WhatsApp verzenden mislukt voor {nette_label}: {e}")
                # raise  # optioneel opnieuw doorgeven
        else:
            print(f"✅ {nette_label}: Waterhoogte {max_value} cm ≤ threshold {threshold} cm — geen melding.")

    # Samenvatting per locatie
    print("\n✅ Samenvatting per locatie:")
    for res in resultaten:
        if "error" in res:
            print(f"- {res['location_code']}: fout – {res['error']}")
        else:
            print(f"- {res['locatie']}: {int(round(res['max_cm']))} cm op {res['when']}")

    # Optioneel: hoogste overall
    geldige = [r for r in resultaten if "error" not in r]
    if geldige:
        top = max(geldige, key=lambda x: x["max_cm"])
        print(f"\n🏆 Hoogste overall: {int(round(top['max_cm']))} cm bij {top['locatie']} op {top['when']}")


if __name__ == "__main__":
    main()
