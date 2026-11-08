import os
import sys
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

REQUIRED_KEYS = [
    "creditos_utlizados",
    "creditos_valor",
    "energia_atv_inj_TE_valor",
    "energia_atv_inj_TUSD_valor",
    "bandeira",
    "bandeira_valor",
    "data_vencimento",
    "subtotal",
    "total_a_pagar",
    "leitura_anterior",
    "leitura_atual",
    "tipo_ligacao_eletrica",
    "cnpj-cpf",
    "endereco",
    "CIP_ILUM_PUB_PREF_MUNICIPAL",
    "juros_valor",
    "multa_valor",
    "bandeira_dados",
    "lista_itens_fatura"
]

def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    print("✓ Health check PASSED")

def test_extract_augusto_sergio():
    pdf_path = os.path.join(os.path.dirname(__file__), "share-1792329128706-augusto-sergio-08.25.pdf")
    assert os.path.exists(pdf_path), f"File not found: {pdf_path}"
    
    with open(pdf_path, "rb") as f:
        res = client.post("/extract", files={"file": ("fatura.pdf", f, "application/pdf")})
        
    assert res.status_code == 200, res.text
    data = res.json()
    
    # Check top-level keys
    for k in REQUIRED_KEYS:
        assert k in data, f"Missing key in response: {k}"
        
    # Check output wrapped key (for n8n compatibility)
    assert "output" in data, "Missing 'output' wrapper for n8n compatibility"
    for k in REQUIRED_KEYS:
        assert k in data["output"], f"Missing key in output: {k}"
        
    # Check specific field values
    assert data["bandeira"] == "Vermelha", f"Expected Vermelha, got {data['bandeira']}"
    assert data["bandeira_valor"] == 29.07, f"Expected 29.07, got {data['bandeira_valor']}"
    assert data["data_vencimento"] == "2025-08-14", f"Expected 2025-08-14, got {data['data_vencimento']}"
    assert data["total_a_pagar"] == 265.29, f"Expected 265.29, got {data['total_a_pagar']}"
    assert data["CIP_ILUM_PUB_PREF_MUNICIPAL"] == 65.09, f"Expected 65.09, got {data['CIP_ILUM_PUB_PREF_MUNICIPAL']}"
    assert data["cnpj-cpf"]["cpf"] is True
    assert data["cnpj-cpf"]["cpf_valor"] == "105.432.952-49"
    assert data["cnpj-cpf"]["cnpj_valor"] == "undefined"
    assert data["endereco"]["nome da empresa"] == "AUGUSTO SERGIO FARIA DE MESQUITA"
    assert data["endereco"]["cep"] == "60150-190"
    assert len(data["lista_itens_fatura"]) == 9

    mockup_path = os.path.join(os.path.dirname(__file__), "mockup_resposta.json")
    with open(mockup_path, "r", encoding="utf-8") as mf:
        mockup = json.load(mf)
    assert data["lista_itens_fatura"] == mockup["lista_itens_fatura"], (
        f"Expected {mockup['lista_itens_fatura']}, got {data['lista_itens_fatura']}"
    )
    for item in data["lista_itens_fatura"]:
        assert item["valor_positivo"] is (item["valor"] >= 0), f"Inconsistent item: {item}"
    assert round(sum(item["valor"] for item in data["lista_itens_fatura"]), 2) == data["total_a_pagar"]
    print("✓ Extraction of share-1792329128706-augusto-sergio-08.25.pdf PASSED")

def test_n8n_webhook_endpoint():
    pdf_path = os.path.join(os.path.dirname(__file__), "share-1792329128706-augusto-sergio-08.25.pdf")
    with open(pdf_path, "rb") as f:
        res = client.post("/homo_extracao_enel", files={"file": ("fatura.pdf", f, "application/pdf")})
    assert res.status_code == 200
    data = res.json()
    assert "output" in data
    assert data["output"]["total_a_pagar"] == 265.29
    print("✓ n8n Webhook endpoint /homo_extracao_enel PASSED")

def test_juros_multa_extraction():
    juros_pdf = r"c:\Users\matheus_willamy\Documents\AboboraTech\AJDC\Faturas_teste\fatura_juros\SOCIEDADE BENEFICENTE  PAPICU (3).pdf"
    if os.path.exists(juros_pdf):
        with open(juros_pdf, "rb") as f:
            res = client.post("/extract", files={"file": ("fatura.pdf", f, "application/pdf")})
        assert res.status_code == 200
        data = res.json()
        assert data["juros_valor"] == 0.45, f"Expected 0.45 juros, got {data['juros_valor']}"
        assert data["multa_valor"] == 6.70, f"Expected 6.70 multa, got {data['multa_valor']}"
        assert data["bandeira"] == "Amarela", f"Expected Amarela, got {data['bandeira']}"
        assert data["bandeira_valor"] == 17.07, f"Expected 17.07, got {data['bandeira_valor']}"
        items_by_name = {item["nome_item"]: item for item in data["lista_itens_fatura"]}
        assert items_by_name["Adic. Band. Amarela Comp."] == {
            "nome_item": "Adic. Band. Amarela Comp.",
            "valor": -17.07,
            "valor_positivo": False,
        }
        assert items_by_name["Energia Atv Inj TE oUC 05/2025 mPT"] == {
            "nome_item": "Energia Atv Inj TE oUC 05/2025 mPT",
            "valor": -567.11,
            "valor_positivo": False,
        }
        assert items_by_name["Energia Atv Inj TUSD oUC 05/2025 mPT"] == {
            "nome_item": "Energia Atv Inj TUSD oUC 05/2025 mPT",
            "valor": -822.15,
            "valor_positivo": False,
        }
        print("✓ Extraction with Juros and Multa PASSED")


def test_lista_itens_fatura_negative_values_unit(monkeypatch=None):
    import extractor

    sample_text = """
Itens de Fatura Unid. Quant. Preço unit (R$) Valor (R$)
Energia Ativa Fornecida TE kWh 7.170 0,36187 2.594,60 118,92 2.594,60 20,00% 518,92 0,27291
Energia Ativa Fornecida TUSD kWh 7.170 0,59574 4.271,48 195,79 4.271,48 20,00% 854,29 0,44929
Energia Atv Inj TE oUC 10/2024 mPT kWh 394 0,36181- 142,88- 6,54- 142,88- 20,00% 28,57- 0,27291
Energia Atv Inj TE oUC 11/2024 mPT kWh 6.745 0,36187- 2.440,85- 111,88- 2.440,85- 20,00% 488,17- 0,27291
Energia Atv Inj TUSD oUC 10/2024 mPT kWh 394 0,47655- 188,19- 10,77- 0,00 0,00% 0,00 0,44929
Energia Atv Inj TUSD oUC 11/2024 mPT kWh 6.745 0,47660- 3.214,70- 184,20- 0,00 0,00% 0,00 0,44929
CIP ILUM PUB PREF MUNICIPAL 339,57 0,00 0,00 0,00% 0,00
Subtotal Faturamento 879,46
Subtotal Outros 339,57
TOTAL
1.219,03
"""

    original_extract = extractor.extract_text_from_pdf
    try:
        if monkeypatch is not None:
            monkeypatch.setattr(extractor, "extract_text_from_pdf", lambda _: sample_text)
        else:
            extractor.extract_text_from_pdf = lambda _: sample_text

        parsed = extractor.parse_fatura_pdf("dummy.pdf")
        assert parsed["creditos_valor"] == -5986.62
        assert parsed["lista_itens_fatura"] == [
            {"nome_item": "Energia Ativa Fornecida TE", "valor": 2594.60, "valor_positivo": True},
            {"nome_item": "Energia Ativa Fornecida TUSD", "valor": 4271.48, "valor_positivo": True},
            {"nome_item": "Energia Atv Inj TE oUC 10/2024 mPT", "valor": -142.88, "valor_positivo": False},
            {"nome_item": "Energia Atv Inj TE oUC 11/2024 mPT", "valor": -2440.85, "valor_positivo": False},
            {"nome_item": "Energia Atv Inj TUSD oUC 10/2024 mPT", "valor": -188.19, "valor_positivo": False},
            {"nome_item": "Energia Atv Inj TUSD oUC 11/2024 mPT", "valor": -3214.70, "valor_positivo": False},
            {"nome_item": "CIP ILUM PUB PREF MUNICIPAL", "valor": 339.57, "valor_positivo": True},
        ]
        assert round(sum(i["valor"] for i in parsed["lista_itens_fatura"]), 2) == 1219.03
    finally:
        if monkeypatch is None:
            extractor.extract_text_from_pdf = original_extract

    # Edge cases: leading minus, zero with minus, negative CIP/Juros/Multa
    edge_text = """
Itens de Fatura Unid. Quant. Preço unit (R$) Valor (R$)
Energia Atv Inj TE oUC 01/2025 mPT kWh 100 -0,50 -50,00
Energia Atv Inj TUSD oUC 01/2025 mPT kWh 100 0,00- 0,00-
CIP ILUM PUB PREF MUNICIPAL 10,50- 0,00
Juros Moratórios -1,25 0,00
Multa 2,30- 0,00
Subtotal Faturamento 0,00
TOTAL
0,00
"""
    try:
        if monkeypatch is not None:
            monkeypatch.setattr(extractor, "extract_text_from_pdf", lambda _: edge_text)
        else:
            extractor.extract_text_from_pdf = lambda _: edge_text

        parsed_edge = extractor.parse_fatura_pdf("dummy_edge.pdf")
        assert parsed_edge["lista_itens_fatura"] == [
            {"nome_item": "Energia Atv Inj TE oUC 01/2025 mPT", "valor": -50.0, "valor_positivo": False},
            {"nome_item": "Energia Atv Inj TUSD oUC 01/2025 mPT", "valor": 0.0, "valor_positivo": True},
            {"nome_item": "CIP ILUM PUB PREF MUNICIPAL", "valor": -10.5, "valor_positivo": False},
            {"nome_item": "Juros Moratórios", "valor": -1.25, "valor_positivo": False},
            {"nome_item": "Multa", "valor": -2.3, "valor_positivo": False},
        ]
        # Ensure zero is positive 0.0 (not -0.0)
        import math
        zero_val = parsed_edge["lista_itens_fatura"][1]["valor"]
        assert zero_val == 0.0 and not math.copysign(1.0, zero_val) < 0
    finally:
        if monkeypatch is None:
            extractor.extract_text_from_pdf = original_extract
    print("✓ Negative values and edge cases in lista_itens_fatura PASSED")

if __name__ == "__main__":
    test_health()
    test_extract_augusto_sergio()
    test_n8n_webhook_endpoint()
    test_juros_multa_extraction()
    test_lista_itens_fatura_negative_values_unit()
    print("\nALL API TESTS PASSED SUCCESSFULLY! 🚀")
