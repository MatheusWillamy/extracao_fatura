import os
import io
import re
import json
import logging
from typing import Dict, Any, Union, Optional
import pypdf
import httpx

logger = logging.getLogger("fatura_extractor")
logging.basicConfig(level=logging.INFO)

SYSTEM_PROMPT_TEMPLATE = """creditos_utlizados responder estilo "quantidade": xxxxx, "unidade": "xxx", a informaçao tem como nome saldo utilizado no mês. Na quantiade que é um numero desconsiderar últimos 0 após último ponto, (exemplo 1.000.00 significa mil quantidade.

creditos_valor = Valor de Energia Atv Inj TE oUC + Valor Energia Atv Inj TUSD (todos os valores de TE se tiver mais que um e tbm de TUSD se tiver mais que um) é somatorio disso tudo, responder o valor total

energia_atv_inj_TE_valor responder dessa forma json  "mes": xx, "ano": xx, "valor": xxxx, a informacao está nesse estilo Energia Atv Inj TE oUC xx/xxxx mPT  existe exemplo 10/2023 onde 10 é o mês e 2023 o ano. Lembre de número negativos

energia_atv_inj_TUSD_valor responder dessa forma json  "mes": xx, "ano": xx, "valor": xxxx, a informacao está nesse estilo Energia Atv Inj TUSD oUC xx/xxxx mPT existe exemplo 10/2023 onde 10 é o mês e 2023 o ano. Lembre de número negativos

bandeira_valor se não tiver valor adiconal na bandeira , colocar 0. O valor a ser pego da bandeira valor é o campo Adic. Band. Amarela Comp.

data_vencimento estilo "2024-10-30"

subtotal ( somar subtotal faturamento com subtotal outros) e qualquer outro subtotal que tiver proximo desses. 

 LEITURA ANTERIOR presente na parte DATAS DE  LEITURA - estilo de date "2025-04-15T00:00:00-03:00" lembre de segui os dados do pdf, certo. não adicionar nada a data que está escrita

LEITURA ATUAL presente na parte DATAS DE  LEITURA - estilo de date "2025-04-15T00:00:00-03:00"lembre de segui os dados do pdf, certo.não adicionar nada a data que está escrita

tipo_ligacao_eletrica (localizado em tipo de fornecimento)

CPF/CNPJ responde r em formato json "cpf": true , "cnpj": false , "cpf_valor": "xxxxxxxxx", "cnpj_valor": "xxx" , caso tenho cnpj marcar como true e especificar o valor, e no cpf colocar false e colcoar valor "undefined" em string mesmo.

endereço responda em  assim "nome da empresa": "xxxx", "endereço": "xxxx", "cep": "xxxxx-xxx"

CIP_ILUM_PUB_PREF_MUNICIPAL - valor em numero referente4 a taxa de iluminação, sempre procurar CIP_ILUM_PUB_PREF_MUNICIPAL dentro do documento.

A parte de Juros Moratório é um numero, e é para ser pegue da coluna valor, lembre de reconhecer valores de centavos. O nome do Campo a ser preenchido é juros do valor de Juros Moratórios. Caso não tiver definir como 0.

Campo multa pegar o valor da multa, caso não tiver definir como 0.

E dados da bandeira colocar esses dois valores o adic band e o adicional band, esses valores tem o nome da bandeira incluido no nome deles, para ajudar a encontrar

na lista_itens_fatura, adicionar todos os itens que são lsitado na lista de itens do documento, onde o nome_item é o nome do item completo, de como aparece na fatura, e o valor é o valor referente ao item na fatura. Apenas valores, coloque apenas o valor dentro do campo valor,e especificque se é negativo ou positivo no campo valor_positivo.
"""

JSON_SCHEMA_EXAMPLE = {
    "creditos_utlizados": [{"quantidade": 1111, "unidade": ""}],
    "creditos_valor": 1111,
    "energia_atv_inj_TE_valor": [{"mes": 1, "ano": 1, "valor": 1111}],
    "energia_atv_inj_TUSD_valor": [{"mes": 1, "ano": 1, "valor": 1111}],
    "bandeira": "bandeira",
    "bandeira_valor": 1111,
    "data_vencimento": "2024-10-30",
    "subtotal": 1111,
    "total_a_pagar": 1111,
    "leitura_anterior": "2025-04-15T00:00:00-03:00",
    "leitura_atual": "2025-04-15T00:00:00-03:00",
    "tipo_ligacao_eletrica": "tipo de ligação",
    "cnpj-cpf": {"cpf": True, "cnpj": False, "cpf_valor": "xxxxxxxxx", "cnpj_valor": "xxx"},
    "endereco": {"nome da empresa": "xxxx", "endereço": "xxxx", "cep": "xxxxx-xxx"},
    "CIP_ILUM_PUB_PREF_MUNICIPAL": 1234,
    "juros_valor": 1234,
    "multa_valor": 1234,
    "bandeira_dados": {"adic_band_comp": 1234, "adicional_band": 1234},
    "lista_itens_fatura": [{"nome_item": "nome", "valor": 123, "valor_positivo": True}]
}


def _clean_number(val_str: str) -> float:
    """Converts a Brazilian formatted currency/number string e.g. 1.234,56- or 65,09 to float."""
    if not val_str:
        return 0.0
    s = val_str.strip()
    is_neg = s.endswith('-') or s.startswith('-')
    cleaned = s.replace('-', '').replace('.', '').replace(',', '.')
    try:
        n = float(cleaned)
        return -n if is_neg else n
    except ValueError:
        return 0.0


def extract_text_from_pdf(pdf_source: Union[str, bytes, io.BytesIO]) -> str:
    """Extracts raw text from PDF source."""
    if isinstance(pdf_source, bytes):
        reader = pypdf.PdfReader(io.BytesIO(pdf_source))
    elif isinstance(pdf_source, io.BytesIO):
        reader = pypdf.PdfReader(pdf_source)
    else:
        reader = pypdf.PdfReader(pdf_source)
        
    full_text = ""
    for page in reader.pages:
        full_text += (page.extract_text() or "") + "\n"
    return full_text


def parse_fatura_pdf(pdf_source: Union[str, bytes, io.BytesIO]) -> Dict[str, Any]:
    """
    High-performance deterministic parser for Brazilian energy invoices (Enel standard).
    Extracts all fields matching strictly the requested structure.
    """
    full_text = extract_text_from_pdf(pdf_source)
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # 1. creditos_utlizados
    saldo_match = re.search(r"Saldo utilizado no m[eê]s:\s*([0-9.,]+)\s*([a-zA-Z]+)", full_text, re.IGNORECASE)
    creditos_utilizados = []
    if saldo_match:
        qtd_str = saldo_match.group(1).strip()
        unidade_str = saldo_match.group(2).strip()
        
        # Desconsiderar últimos zeros após último ponto (ex: 1.000.00 -> 1000)
        parts = qtd_str.split('.')
        if len(parts) > 2:
            val_clean = "".join(parts[:-1]) + "." + parts[-1]
        elif len(parts) == 2:
            val_clean = qtd_str
        else:
            val_clean = qtd_str.replace(',', '.')
            
        try:
            val_float = float(val_clean)
            if val_float.is_integer():
                qtd_num = int(val_float)
            else:
                qtd_num = round(val_float, 2)
        except Exception:
            qtd_num = 0
            
        creditos_utilizados.append({
            "quantidade": qtd_num,
            "unidade": unidade_str
        })
    else:
        creditos_utilizados.append({
            "quantidade": 0,
            "unidade": "kWh"
        })

    # 2. Extract items from invoice table
    lista_itens = []
    start_idx = -1
    end_idx = -1
    for i, l in enumerate(lines):
        if "itens de fatura" in l.lower():
            start_idx = i
        elif "subtotal faturamento" in l.lower() and start_idx != -1:
            end_idx = i
            break
            
    raw_item_lines = []
    if start_idx != -1 and end_idx != -1:
        for l in lines[start_idx+1:end_idx]:
            if any(h in l.lower() for h in ["com tributos", "valor (r$)", "pis/cofins", "base calc", "icms", "alíquota", "tarifa", "unit (r$)"]):
                continue
            raw_item_lines.append(l)

    energia_te_items = []
    energia_tusd_items = []
    
    cip_valor = 0.0
    juros_valor = 0.0
    multa_valor = 0.0
    
    adic_band_comp_val = 0.0
    adicional_band_val = 0.0
    detected_band_color = None
    
    for l in raw_item_lines:
        # Check CIP ILUM PUB PREF MUNICIPAL
        m_cip = re.search(r"CIP ILUM PUB PREF MUNICIPAL\s+([0-9.,]+)", l, re.IGNORECASE)
        if m_cip:
            val = abs(_clean_number(m_cip.group(1)))
            cip_valor = val
            lista_itens.append({
                "nome_item": "CIP ILUM PUB PREF MUNICIPAL",
                "valor": val,
                "valor_positivo": True
            })
            continue
            
        # Check Juros Moratórios
        m_juros = re.search(r"Juros Morat[oó]rios\s+([0-9.,]+)", l, re.IGNORECASE)
        if m_juros:
            val = abs(_clean_number(m_juros.group(1)))
            juros_valor = val
            lista_itens.append({
                "nome_item": "Juros Moratórios",
                "valor": val,
                "valor_positivo": True
            })
            continue
            
        # Check Multa
        m_multa = re.search(r"^Multa\s+([0-9.,]+)", l, re.IGNORECASE)
        if m_multa:
            val = abs(_clean_number(m_multa.group(1)))
            multa_valor = val
            lista_itens.append({
                "nome_item": "Multa",
                "valor": val,
                "valor_positivo": True
            })
            continue

        # Standard energy item line:
        # <nome_item> kWh <quant> <preco_unit>[-] <valor>[-] ...
        m_kwh = re.search(r"^(.*?)\s+kWh\s+([0-9.,]+)\s+([0-9.,]+-?)\s+([0-9.,]+-?)", l)
        if m_kwh:
            nome_item = m_kwh.group(1).strip()
            valor_raw = m_kwh.group(4).strip()
            is_neg = valor_raw.endswith('-') or valor_raw.startswith('-')
            val_clean = valor_raw.replace('-', '').replace('.', '').replace(',', '.')
            try:
                val_num = round(float(val_clean), 2)
            except Exception:
                val_num = 0.0
            
            lista_itens.append({
                "nome_item": nome_item,
                "valor": val_num,
                "valor_positivo": not is_neg
            })
            
            # Energia Atv Inj TE oUC
            if "Energia Atv Inj TE oUC" in nome_item:
                m_date = re.search(r"(\d{2})/(\d{4})", nome_item)
                if m_date:
                    mes = int(m_date.group(1))
                    ano = int(m_date.group(2))
                    item_val = -val_num if is_neg else val_num
                    energia_te_items.append({
                        "mes": mes,
                        "ano": ano,
                        "valor": item_val
                    })
                    
            # Energia Atv Inj TUSD oUC
            elif "Energia Atv Inj TUSD oUC" in nome_item:
                m_date = re.search(r"(\d{2})/(\d{4})", nome_item)
                if m_date:
                    mes = int(m_date.group(1))
                    ano = int(m_date.group(2))
                    item_val = -val_num if is_neg else val_num
                    energia_tusd_items.append({
                        "mes": mes,
                        "ano": ano,
                        "valor": item_val
                    })
                    
            if "Adic. Band." in nome_item and "Comp." in nome_item:
                adic_band_comp_val = -val_num if is_neg else val_num
                m_col = re.search(r"Adic\.\s*Band\.\s*([A-Za-z]+)\s*Comp\.", nome_item, re.IGNORECASE)
                if m_col:
                    detected_band_color = m_col.group(1).capitalize()
            elif "Adicional Band." in nome_item:
                adicional_band_val = -val_num if is_neg else val_num
                m_col = re.search(r"Adicional\s*Band\.\s*([A-Za-z]+)", nome_item, re.IGNORECASE)
                if m_col:
                    detected_band_color = m_col.group(1).capitalize()

    # Fallback search for CIP / Juros / Multa in whole text if not in table
    if cip_valor == 0.0:
        m_cip_any = re.search(r"CIP ILUM PUB PREF MUNICIPAL\s+([0-9.,]+)", full_text, re.IGNORECASE)
        if m_cip_any:
            cip_valor = abs(_clean_number(m_cip_any.group(1)))
            
    if juros_valor == 0.0:
        m_juros_any = re.search(r"Juros Morat[oó]rios\s+([0-9.,]+)", full_text, re.IGNORECASE)
        if m_juros_any:
            juros_valor = abs(_clean_number(m_juros_any.group(1)))
            
    if multa_valor == 0.0:
        m_multa_any = re.search(r"\bMulta\s+([0-9.,]+)", full_text, re.IGNORECASE)
        if m_multa_any:
            multa_valor = abs(_clean_number(m_multa_any.group(1)))

    # 3. creditos_valor = Valor TE + Valor TUSD (all)
    soma_te = sum(x["valor"] for x in energia_te_items)
    soma_tusd = sum(x["valor"] for x in energia_tusd_items)
    creditos_valor = round(soma_te + soma_tusd, 2)
    
    # 4. bandeira and bandeira_valor
    if detected_band_color:
        bandeira_str = detected_band_color
    else:
        m_band = re.search(r"Band(?:eira)?\.?\s*Tarif\.?:\s*([A-Za-z]+)", full_text, re.IGNORECASE)
        if m_band:
            bandeira_str = m_band.group(1).capitalize()
        else:
            m_band2 = re.search(r"Bandeira\s+([A-Za-z]+)", full_text, re.IGNORECASE)
            if m_band2:
                bandeira_str = m_band2.group(1).capitalize()
            elif "amarela" in full_text.lower():
                bandeira_str = "Amarela"
            elif "vermelha" in full_text.lower():
                bandeira_str = "Vermelha"
            elif "verde" in full_text.lower():
                bandeira_str = "Verde"
            else:
                bandeira_str = "Verde"
            
    # bandeira_valor:
    # "se não tiver valor adiconal na bandeira , colocar 0. O valor a ser pego da bandeira valor é o campo Adic. Band. Amarela Comp."
    bandeira_valor = abs(adic_band_comp_val) if adic_band_comp_val != 0.0 else 0
    bandeira_dados = {
        "adic_band_comp": adic_band_comp_val,
        "adicional_band": adicional_band_val
    }

    # 5. data_vencimento
    data_vencimento = ""
    m_venc = re.search(r"Data Vencimento:\s*(\d{2})/(\d{2})/(\d{4})", full_text, re.IGNORECASE)
    if not m_venc:
        m_venc = re.search(r"\d{2}/\d{4}\s+(\d{2})/(\d{2})/(\d{4})\s+R\$\s*[0-9.,]+", full_text)
    if m_venc:
        d, m, y = m_venc.group(1), m_venc.group(2), m_venc.group(3)
        data_vencimento = f"{y}-{m}-{d}"

    # 6. subtotal
    subtotais = []
    for l in lines:
        m_sub = re.search(r"Subtotal\s+[A-Za-zÀ-ÿ]+\s+([0-9.,]+)", l, re.IGNORECASE)
        if m_sub:
            val = abs(_clean_number(m_sub.group(1)))
            subtotais.append(val)
    subtotal = round(sum(subtotais), 2) if subtotais else 0.0

    # 7. total_a_pagar
    total_a_pagar = 0.0
    m_tot = re.search(r"Valor do Documento:\s*R\$\s*([0-9.,]+)", full_text, re.IGNORECASE)
    if not m_tot:
        m_tot = re.search(r"\bTOTAL\s*\n\s*([0-9.,]+)", full_text)
    if m_tot:
        total_a_pagar = abs(_clean_number(m_tot.group(1)))

    # If subtotal not found, fallback to total_a_pagar
    if subtotal == 0.0 and total_a_pagar != 0.0:
        subtotal = total_a_pagar

    # 8. leitura_anterior & leitura_atual & tipo_ligacao_eletrica
    m_leituras = re.search(r"(TRIF[AÁ]SICO|MONOF[AÁ]SICO|BIF[AÁ]SICO)\s+(\d{2})/(\d{2})/(\d{4})\s+(\d{2})/(\d{2})/(\d{4})", full_text, re.IGNORECASE)
    tipo_ligacao = ""
    leitura_anterior = ""
    leitura_atual = ""
    if m_leituras:
        tipo_ligacao = m_leituras.group(1).upper()
        d1, m1, y1 = m_leituras.group(2), m_leituras.group(3), m_leituras.group(4)
        d2, m2, y2 = m_leituras.group(5), m_leituras.group(6), m_leituras.group(7)
        leitura_anterior = f"{y1}-{m1}-{d1}T00:00:00-03:00"
        leitura_atual = f"{y2}-{m2}-{d2}T00:00:00-03:00"

    # 9. cnpj-cpf & 10. endereco
    cpf_cnpj_info = {"cpf": False, "cnpj": False, "cpf_valor": "undefined", "cnpj_valor": "undefined"}
    nome_empresa = ""
    endereco_str = ""
    cep_str = ""
    
    for i, l in enumerate(lines):
        if re.search(r"(TRIF[AÁ]SICO|MONOF[AÁ]SICO|BIF[AÁ]SICO)\s+\d{2}/\d{2}/\d{4}", l, re.IGNORECASE):
            if i + 1 < len(lines):
                nome_empresa = lines[i+1].strip()
            
            addr_parts = []
            for j in range(i+2, min(i+8, len(lines))):
                line_j = lines[j]
                if "CPF/CNPJ:" in line_j:
                    m_cpf = re.search(r"CPF/CNPJ:\s*([0-9.\-\/]+)", line_j)
                    if m_cpf:
                        doc_str = m_cpf.group(1).strip()
                        digits = re.sub(r"\D", "", doc_str)
                        if len(digits) == 11:
                            cpf_cnpj_info = {
                                "cpf": True,
                                "cnpj": False,
                                "cpf_valor": doc_str,
                                "cnpj_valor": "undefined"
                            }
                        elif len(digits) == 14:
                            cpf_cnpj_info = {
                                "cpf": False,
                                "cnpj": True,
                                "cpf_valor": "undefined",
                                "cnpj_valor": doc_str
                            }
                    break
                elif "CEP:" in line_j:
                    m_cep = re.search(r"CEP:\s*(\d{5}-\d{3})", line_j)
                    if m_cep:
                        cep_str = m_cep.group(1)
                else:
                    addr_parts.append(line_j.strip())
            endereco_str = " ".join(addr_parts)
            break

    # Fallback CPF/CNPJ
    if cpf_cnpj_info["cpf_valor"] == "undefined" and cpf_cnpj_info["cnpj_valor"] == "undefined":
        m_doc = re.search(r"CPF/CNPJ:\s*([0-9.\-\/]+)", full_text)
        if m_doc:
            doc_str = m_doc.group(1).strip()
            digits = re.sub(r"\D", "", doc_str)
            if len(digits) == 11:
                cpf_cnpj_info = {
                    "cpf": True,
                    "cnpj": False,
                    "cpf_valor": doc_str,
                    "cnpj_valor": "undefined"
                }
            elif len(digits) == 14:
                cpf_cnpj_info = {
                    "cpf": False,
                    "cnpj": True,
                    "cpf_valor": "undefined",
                    "cnpj_valor": doc_str
                }

    # Fallback CEP
    if not cep_str:
        m_ceps = re.findall(r"CEP:\s*(\d{5}-\d{3})", full_text)
        cust_ceps = [c for c in m_ceps if c != "60135-040"]
        if cust_ceps:
            cep_str = cust_ceps[0]
        elif m_ceps:
            cep_str = m_ceps[-1]

    endereco = {
        "nome da empresa": nome_empresa,
        "endereço": endereco_str,
        "cep": cep_str
    }

    result = {
        "creditos_utlizados": creditos_utilizados,
        "creditos_valor": creditos_valor,
        "energia_atv_inj_TE_valor": energia_te_items,
        "energia_atv_inj_TUSD_valor": energia_tusd_items,
        "bandeira": bandeira_str,
        "bandeira_valor": bandeira_valor,
        "data_vencimento": data_vencimento,
        "subtotal": subtotal,
        "total_a_pagar": total_a_pagar,
        "leitura_anterior": leitura_anterior,
        "leitura_atual": leitura_atual,
        "tipo_ligacao_eletrica": tipo_ligacao,
        "cnpj-cpf": cpf_cnpj_info,
        "endereco": endereco,
        "CIP_ILUM_PUB_PREF_MUNICIPAL": cip_valor,
        "juros_valor": juros_valor,
        "multa_valor": multa_valor,
        "bandeira_dados": bandeira_dados,
        "lista_itens_fatura": lista_itens
    }
    return result


async def extract_fatura_with_ai(
    pdf_text: str,
    api_key: Optional[str] = None,
    provider: str = "gemini",
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extracts invoice data using an LLM (Gemini or OpenRouter/OpenAI compatible),
    mimicking the exact LangChain Information Extractor node from n8n.
    """
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("Nenhuma chave de API de IA configurada (GEMINI_API_KEY, OPENROUTER_API_KEY ou OPENAI_API_KEY).")

    prompt = f"""{SYSTEM_PROMPT_TEMPLATE}

Schema de saída estritamente em JSON:
{json.dumps(JSON_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

Texto extraído da fatura:
---
{pdf_text[:12000]}
---
Responda EXCLUSIVAMENTE com o objeto JSON válido correspondente, sem explicações adicionais ou blocos markdown de texto exterior.
"""

    # 1. Google Gemini API
    if provider == "gemini" or (os.getenv("GEMINI_API_KEY") and not os.getenv("OPENROUTER_API_KEY")):
        model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(raw_text)

    # 2. OpenRouter or OpenAI
    url = "https://openrouter.ai/api/v1/chat/completions" if "openrouter" in provider.lower() else "https://api.openai.com/v1/chat/completions"
    model_name = model or ("google/gemma-2-27b-it:free" if "openrouter" in url else "gpt-4o-mini")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "Você é um extrator de dados de faturas estritamente preciso que responde apenas JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["choices"][0]["message"]["content"]
        return json.loads(raw_text)


async def extract_fatura(
    pdf_source: Union[str, bytes, io.BytesIO],
    mode: str = "auto",
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Unified extraction entrypoint.
    Modes:
      - 'structured': pure deterministic parser (fast, 0 cost, highly accurate for standard Enel bills).
      - 'ai': uses LLM (requires API key).
      - 'auto': runs structured parser first; if text is empty/corrupt, falls back to AI.
    """
    if mode == "ai":
        pdf_text = extract_text_from_pdf(pdf_source)
        return await extract_fatura_with_ai(pdf_text, api_key=api_key)

    try:
        result = parse_fatura_pdf(pdf_source)
        # Check basic sanity: if total_a_pagar == 0 and no items found, and mode is auto and key present, try AI
        if mode == "auto" and result["total_a_pagar"] == 0.0 and len(result["lista_itens_fatura"]) == 0:
            if api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY"):
                logger.info("Structured parser found no items; falling back to AI...")
                pdf_text = extract_text_from_pdf(pdf_source)
                return await extract_fatura_with_ai(pdf_text, api_key=api_key)
        return result
    except Exception as e:
        logger.warning(f"Structured parser failed: {e}. Falling back to AI if available.")
        if mode == "auto" and (api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENROUTER_API_KEY")):
            pdf_text = extract_text_from_pdf(pdf_source)
            return await extract_fatura_with_ai(pdf_text, api_key=api_key)
        raise e


def format_api_response(data: Dict[str, Any], wrap_output: bool = True) -> Dict[str, Any]:
    """
    Guarantees compatibility with both n8n (which outputs { 'output': { ... } })
    and direct consumers, including the 'cnpj_cpf' alias used in FlutterFlow.
    """
    # Ensure all expected keys exist
    for key, default_val in JSON_SCHEMA_EXAMPLE.items():
        if key not in data:
            data[key] = default_val

    # Add cnpj_cpf alias inside data if not present (FlutterFlow looks for $.cnpj_cpf or $.cnpj-cpf)
    if "cnpj_cpf" not in data and "cnpj-cpf" in data:
        data["cnpj_cpf"] = data["cnpj-cpf"]

    if wrap_output:
        # Provide both top-level and nested 'output' so that:
        # - caller.total_a_pagar works
        # - caller.output.total_a_pagar works
        response = dict(data)
        response["output"] = dict(data)
        return response
    return data
