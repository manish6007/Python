"""Tests for the broker CSV and CAS importers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import importers as imp  # noqa: E402

# Header rows in the shape real brokers export them.
ZERODHA = "Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L"
GROWW = "Stock Name,ISIN,Quantity,Average buying price,Buy value,Closing price"
UPSTOX = "Company Name,Symbol,Quantity,Average Price,Last Traded Price"
ICICI = "Scrip Name,Scrip Code,Holding Qty,Average Cost,Market Price,Market Value"
OURS = "identifier,name,units,avg_cost,last_price"


def test_headers_from_each_broker_map_to_the_same_fields():
    for header in (ZERODHA, GROWW, UPSTOX, ICICI, OURS):
        m = imp.sniff_columns(header.split(","))
        assert "units" in m, header
        assert "name" in m or "identifier" in m, header
        assert "avg_cost" in m or "invested" in m, header


def test_zerodha_style_maps_the_expected_columns():
    # Zerodha's "Instrument" column holds the ticker, so identifier is the
    # right target; build_rows falls back to it when no name column exists.
    m = imp.sniff_columns(ZERODHA.split(","))
    assert m["identifier"] == "Instrument"
    assert m["units"] == "Qty."
    assert m["avg_cost"] == "Avg. cost"
    assert m["last_price"] == "LTP"
    assert m["current_value"] == "Cur. val"


def test_name_falls_back_to_the_ticker_when_there_is_no_name_column():
    rows, _ = imp.build_rows([{"Instrument": "RELIANCE", "Qty.": "10"}],
                             {"identifier": "Instrument", "units": "Qty."})
    assert rows[0]["name"] == "RELIANCE" and rows[0]["identifier"] == "RELIANCE"


def test_a_field_is_never_claimed_by_two_columns():
    m = imp.sniff_columns(["Price", "Last Price", "Quantity", "Name"])
    assert len(set(m.values())) == len(m)


def test_number_parsing_handles_indian_money_formatting():
    assert imp.to_number("1,23,456.78") == 123456.78
    assert imp.to_number("₹ 2,400") == 2400
    assert imp.to_number("(1,200)") == -1200
    assert imp.to_number("") is None
    assert imp.to_number("-") is None
    assert imp.to_number("N/A") is None


def test_reading_a_csv_skips_title_rows_above_the_header():
    data = (b"Holdings statement\n"
            b"Generated on 2026-08-25\n\n"
            b"Instrument,Qty.,Avg. cost,LTP\n"
            b"RELIANCE,10,2400,2950\n"
            b"TITAN,8,4494,5079\n")
    headers, rows = imp.read_table(data, "holdings.csv")
    assert headers == ["Instrument", "Qty.", "Avg. cost", "LTP"]
    assert len(rows) == 2 and rows[0]["Instrument"] == "RELIANCE"


def test_build_rows_derives_average_cost_from_invested_value():
    recs = [{"Stock Name": "INFY", "Quantity": "10", "Buy value": "12,000"}]
    mapping = {"name": "Stock Name", "units": "Quantity",
               "invested": "Buy value"}
    rows, skipped = imp.build_rows(recs, mapping)
    assert not skipped
    assert rows[0]["avg_cost"] == 1200 and rows[0]["invested"] == 12000


def test_build_rows_derives_price_from_current_value():
    recs = [{"n": "X", "q": "4", "cv": "40,000"}]
    rows, _ = imp.build_rows(recs, {"name": "n", "units": "q",
                                    "current_value": "cv"})
    assert rows[0]["last_price"] == 10000


def test_rows_without_quantity_are_reported_not_dropped_silently():
    recs = [{"Instrument": "RELIANCE", "Qty.": "10", "Avg. cost": "2400"},
            {"Instrument": "FUSION", "Qty.": "0", "Avg. cost": "229"},
            {"Instrument": "", "Qty.": "5", "Avg. cost": "1"}]
    rows, skipped = imp.build_rows(
        recs, {"name": "Instrument", "units": "Qty.", "avg_cost": "Avg. cost"})
    assert len(rows) == 1 and rows[0]["name"] == "RELIANCE"
    assert len(skipped) == 2
    assert any("FUSION" in s for s in skipped)


def test_end_to_end_zerodha_csv():
    data = (b"Instrument,Qty.,Avg. cost,LTP,Cur. val\n"
            b"RELIANCE,40,2350.00,2960.00,118400.00\n"
            b"HDFCBANK,60,1490.00,1710.00,102600.00\n")
    headers, recs = imp.read_table(data, "z.csv")
    rows, skipped = imp.build_rows(recs, imp.sniff_columns(headers))
    assert not skipped and len(rows) == 2
    assert rows[0]["units"] == 40 and rows[0]["avg_cost"] == 2350
    assert rows[0]["current_value"] == 118400


# ---- CAS ----------------------------------------------------------------
CAS_TEXT = """
Consolidated Account Statement
Folio No: 12345678 / 21
HDFCFC-HDFC Flexi Cap Fund - Growth Plan (Advisor: DIRECT) Registrar : CAMS
ISIN: INF179K01608
Opening Unit Balance: 0.000
01-Apr-2023 Purchase 100,000.00 55.1234 1,814.55
Closing Unit Balance: 1,814.550 NAV on 31-Mar-2026: INR 81.2345
Total Cost Value: INR 100,000.00
Valuation on 31-Mar-2026: INR 147,410.20

Folio No: 99887766 / 0
PPFAS-Parag Parikh Flexi Cap Fund - Direct Growth Registrar : KFINTECH
Closing Unit Balance: 512.330 NAV on 31-Mar-2026: INR 89.8800
Valuation on 31-Mar-2026: INR 46,048.02

Folio No: 55554444 / 3
OLD-A Closed Scheme - Growth Registrar : CAMS
Closing Unit Balance: 0.000
"""


def test_cas_parses_folios_with_a_balance():
    rows, notes = imp.parse_cas(CAS_TEXT)
    assert len(rows) == 2                       # the closed folio is skipped
    a = rows[0]
    assert a["identifier"].startswith("12345678")
    assert a["units"] == 1814.55
    assert a["last_price"] == 81.2345
    assert a["invested"] == 100000
    assert a["current_value"] == 147410.20
    assert a["avg_cost"] == round(100000 / 1814.55, 4)
    assert "HDFC Flexi Cap Fund" in a["name"]
    assert a["asset_class"] == "mutual_fund"


def test_cas_derives_nav_when_only_a_valuation_is_given():
    rows, _ = imp.parse_cas(
        "Folio No: 111 / 0\nX-Some Fund - Growth Registrar : CAMS\n"
        "Closing Unit Balance: 100.000\n"
        "Valuation on 31-Mar-2026: INR 25,000.00\n")
    assert rows[0]["last_price"] == 250.0


def test_cas_reports_when_it_finds_nothing():
    rows, notes = imp.parse_cas("Some unrelated PDF text")
    assert rows == [] and notes


def test_cas_wrong_password_is_reported_clearly():
    import io as _io

    import pytest
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Folio No: 1")
    c.save()
    w = PdfWriter(clone_from=_io.BytesIO(buf.getvalue()))
    w.encrypt("right-one", algorithm="AES-256")
    out = _io.BytesIO()
    w.write(out)
    with pytest.raises(PermissionError):
        imp.extract_cas_text(out.getvalue(), "wrong-one")
    assert "Folio No" in imp.extract_cas_text(out.getvalue(), "right-one")


# ---- CAS summary (the table layout CAMS/KFintech actually sends) ----------
SUMMARY = """Folio No. ISIN Scheme Name Cost Value (INR) Unit Balance NAV Date NAV (INR) Market Value (INR) Registrar
90722941761/0INF846K01EW2 128TSDGG - Axis ELSS Tax Saver Fund -
Direct Growth (Non Demat) 537,500.000 7,763.079 25-Aug-2026 112.6609 874,595.47 KFINTECH
4274832/68 INF740K01PX1 D782 - DSP Mid Cap Fund - Direct Plan -
Growth (formerly DSP Small and Mid Cap
Fund) (Non-Demat) 363,000.000 4,280.894 25-Aug-2026 178.295 763,262.00 CAMS
Total 900,500.00 1,637,857.47
"""


def test_summary_layout_is_detected_and_parsed():
    rows, notes, layout = imp.parse_cas_any(SUMMARY)
    assert layout == "summary" and len(rows) == 2
    a = rows[0]
    assert a["identifier"] == "90722941761/0"      # folio, ISIN split off
    assert a["isin"] == "INF846K01EW2"
    assert a["units"] == 7763.079
    assert a["invested"] == 537500
    assert a["last_price"] == 112.6609
    assert a["current_value"] == 874595.47
    assert a["registrar"] == "KFINTECH"
    assert a["name"].startswith("Axis ELSS Tax Saver Fund")   # code prefix gone
    assert "Non Demat" not in a["name"]


def test_folio_glued_to_isin_is_still_read():
    """The bug that silently dropped 3 of 12 rows: no word boundary."""
    rows, _, _ = imp.parse_cas_any(SUMMARY)
    glued = [r for r in rows if r["isin"] == "INF846K01EW2"]
    assert len(glued) == 1 and glued[0]["identifier"] == "90722941761/0"


def test_totals_mismatch_is_reported_not_swallowed():
    broken = SUMMARY.replace("Total 900,500.00 1,637,857.47",
                             "Total 1,500,000.00 2,900,000.00")
    rows, notes, _ = imp.parse_cas_any(broken)
    assert rows
    assert any("not read" in n or "difference" in n for n in notes)


def test_totals_that_agree_produce_no_warning():
    rows, notes, _ = imp.parse_cas_any(SUMMARY)
    assert not [n for n in notes if "difference" in n]


def test_summary_skips_exited_schemes_with_no_units():
    text = SUMMARY + ("55554444/3 INF200K01T51 LD346G - Closed Fund "
                      "0.000 0.000 25-Aug-2026 0.000 0.00 CAMS\n")
    rows, _, _ = imp.parse_cas_any(text)
    assert all(r["units"] > 0 for r in rows)


def test_amfi_dump_yields_an_isin_index():
    import pricing
    navs, by_isin = pricing.parse_amfi_dump(
        "120503;INF846K01EW2;INF846K01FA4;Axis ELSS;112.6609;25-Aug-2026\n"
        "122639;INF879O01027;N.A.;PPFAS Flexi;91.1854;25-Aug-2026\n"
        "garbage\n")
    assert navs["120503"]["nav"] == 112.6609
    assert by_isin["INF846K01EW2"] == "120503"
    assert by_isin["INF846K01FA4"] == "120503"     # both ISIN columns indexed
    assert "N.A." not in by_isin
