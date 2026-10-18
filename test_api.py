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
        print("✓ Extraction with Juros and Multa PASSED")

if __name__ == "__main__":
    test_health()
    test_extract_augusto_sergio()
    test_n8n_webhook_endpoint()
    test_juros_multa_extraction()
    print("\nALL API TESTS PASSED SUCCESSFULLY! 🚀")
