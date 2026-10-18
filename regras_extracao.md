# Regras de Extração de Dados de Fatura de Energia (Enel)

Este documento especifica formalmente as regras de negócio, a origem de cada campo no documento PDF e a tipagem estrita para a extração automatizada de dados de faturas de energia elétrica (padrão Enel / Distribuição Ceará e compatíveis).

A estrutura de saída foi desenhada para compatibilidade total com os fluxos do **n8n** e consumo direto no **FlutterFlow** (ações `parseAllFaturaData` e `processFaturaData`).

---

## 1. Estrutura Canônica do JSON de Saída

```json
{
  "creditos_utlizados": [
    {
      "quantidade": 453.26,
      "unidade": "kWh"
    }
  ],
  "creditos_valor": -304.62,
  "energia_atv_inj_TE_valor": [
    {
      "mes": 8,
      "ano": 2025,
      "valor": -145.86
    }
  ],
  "energia_atv_inj_TUSD_valor": [
    {
      "mes": 8,
      "ano": 2025,
      "valor": -158.76
    }
  ],
  "bandeira": "Vermelha",
  "bandeira_valor": 29.07,
  "data_vencimento": "2025-08-14",
  "subtotal": 265.29,
  "total_a_pagar": 265.29,
  "leitura_anterior": "2025-07-03T00:00:00-03:00",
  "leitura_atual": "2025-08-04T00:00:00-03:00",
  "tipo_ligacao_eletrica": "TRIFÁSICO",
  "cnpj-cpf": {
    "cpf": true,
    "cnpj": false,
    "cpf_valor": "105.432.952-49",
    "cnpj_valor": "undefined"
  },
  "endereco": {
    "nome da empresa": "AUGUSTO SERGIO FARIA DE MESQUITA",
    "endereço": "RU MARCOS MACEDO 00843 AP 1101 ALDEOTA FORTALEZA CE",
    "cep": "60150-190"
  },
  "CIP_ILUM_PUB_PREF_MUNICIPAL": 65.09,
  "juros_valor": 0.0,
  "multa_valor": 0.0,
  "bandeira_dados": {
    "adic_band_comp": -29.07,
    "adicional_band": 34.37
  },
  "lista_itens_fatura": [
    {
      "nome_item": "CIP ILUM PUB PREF MUNICIPAL",
      "valor": 65.09,
      "valor_positivo": true
    },
    {
      "nome_item": "Adic. Band. Vermelha Comp.",
      "valor": 29.07,
      "valor_positivo": false
    }
  ]
}
```

---

## 2. Detalhamento Campo a Campo

### 2.1. `creditos_utlizados`
* **Tipo:** `List[Dict[str, Union[int, float, str]]]`
* **Origem no PDF:** Bloco de informações de créditos/energia injetada: `"Saldo utilizado no mês: <quantidade> <unidade>"`.
* **Regras de Formatação:**
  - `quantidade`: Deve ser um número (`int` ou `float`). Desconsiderar zeros não significativos após o último ponto decimal. Exemplos:
    - `"1.000.00"` -> `1000`
    - `"7.140.00"` -> `7140`
    - `"1.660.20"` -> `1660.2`
    - `"453.26"` -> `453.26`
  - `unidade`: Captura a unidade especificada no texto (geralmente `"kWh"`).
  - Caso não exista informação de saldo utilizado, preencher com `[{"quantidade": 0, "unidade": "kWh"}]`.

---

### 2.2. `creditos_valor`
* **Tipo:** `float` (número decimal)
* **Definição:** Somatório aritmético de todos os valores de injeção **TE** (`Energia Atv Inj TE oUC`) e **TUSD** (`Energia Atv Inj TUSD oUC`).
* **Regra de Sinal:** Como são créditos injetados abatidos na fatura, os valores constam com sinal negativo no PDF. A soma preserva o valor negativo correspondente (ex: `-145.86 + -158.76 = -304.62`).
* **Observação de Consumo no Frontend:** O FlutterFlow aplica `.abs()` para obter o montante base de cálculo de desconto.

---

### 2.3. `energia_atv_inj_TE_valor`
* **Tipo:** `List[Dict[str, Union[int, float]]]`
* **Origem no PDF:** Linhas da tabela de itens de fatura que contêm `"Energia Atv Inj TE oUC <mes>/<ano> ..."`.
* **Estrutura de cada item:**
  - `"mes"`: Mês de competência da injeção (`int`, 1 a 12).
  - `"ano"`: Ano de competência da injeção (`int`, ex: 2024, 2025).
  - `"valor"`: Valor financeiro do item em R$, mantendo o sinal negativo (`float`, ex: `-145.86`).
* **Múltiplas Ocorrências:** Se a fatura tiver créditos de meses anteriores (ex: 10/2024 e 11/2024), a lista deve conter todos os itens individuais.

---

### 2.4. `energia_atv_inj_TUSD_valor`
* **Tipo:** `List[Dict[str, Union[int, float]]]`
* **Origem no PDF:** Linhas da tabela de itens que contêm `"Energia Atv Inj TUSD oUC <mes>/<ano> ..."`.
* **Estrutura de cada item:**
  - `"mes"`: Mês de competência da injeção (`int`, 1 a 12).
  - `"ano"`: Ano de competência da injeção (`int`, ex: 2024, 2025).
  - `"valor"`: Valor financeiro em R$, mantendo o sinal negativo (`float`, ex: `-158.76`).
* **Múltiplas Ocorrências:** Lista todos os itens de TUSD injetados presentes na fatura.

---

### 2.5. `bandeira`
* **Tipo:** `str`
* **Valores Possíveis:** `"Verde"`, `"Amarela"`, `"Vermelha"`, etc.
* **Origem no PDF:**
  1. Verificação prioritária na linha de itens de compensação/adicional de bandeira (`"Adicional Band. <Cor>"` ou `"Adic. Band. <Cor> Comp."`).
  2. Bloco textual informativo `"Períodos: Band. Tarif.: <Cor>"` ou `"Bandeira <cor>"`.

---

### 2.6. `bandeira_valor`
* **Tipo:** `float`
* **Regra:** Se não houver cobrança adicional de bandeira (ex: Bandeira Verde), o valor deve ser estritamente `0` (ou `0.0`).
* **Origem:** Extraído do valor do item de compensação de bandeira (`Adic. Band. <Cor> Comp.`). Valor retornado em módulo/positivo (`abs`).

---

### 2.7. `data_vencimento`
* **Tipo:** `str` (Formato estrito `YYYY-MM-DD`, ex: `"2025-08-14"`).
* **Origem no PDF:** Campo `"Data Vencimento:"` no canhoto ou cabeçalho de cobrança da fatura.

---

### 2.8. `subtotal`
* **Tipo:** `float`
* **Origem no PDF:** Soma dos valores de `"Subtotal Faturamento"`, `"Subtotal Outros"` e qualquer outro subtotal próximo na fatura.
* **Exemplo:** `200.20 + 65.09 = 265.29`.

---

### 2.9. `total_a_pagar`
* **Tipo:** `float`
* **Origem no PDF:** Campo `"TOTAL"` ou `"Valor do Documento: R$ ..."`.

---

### 2.10. `leitura_anterior` e `leitura_atual`
* **Tipo:** `str` (Formato ISO 8601 com fuso horário `-03:00`, ex: `"2025-07-03T00:00:00-03:00"`).
* **Origem no PDF:** Bloco **DATAS DE LEITURA** no cabeçalho do documento:
  - `LEITURA ANTERIOR`: Primeira data (`DD/MM/AAAA` convertida para `AAAA-MM-DDT00:00:00-03:00`).
  - `LEITURA ATUAL`: Segunda data (`DD/MM/AAAA` convertida para `AAAA-MM-DDT00:00:00-03:00`).
* **Atenção:** Seguir rigorosamente os dados presentes no documento sem inventar ou truncar datas.

---

### 2.11. `tipo_ligacao_eletrica`
* **Tipo:** `str`
* **Origem no PDF:** Campo de `"TIPO DE FORNECIMENTO"` / classificação.
* **Exemplos típicos:** `"TRIFÁSICO"`, `"MONOFÁSICO"`, `"BIFÁSICO"`.

---

### 2.12. `cnpj-cpf`
* **Tipo:** `Dict[str, Any]`
* **Estrutura Canônica:**
  - Se for **CPF** (11 dígitos):
    ```json
    {
      "cpf": true,
      "cnpj": false,
      "cpf_valor": "105.432.952-49",
      "cnpj_valor": "undefined"
    }
    ```
  - Se for **CNPJ** (14 dígitos):
    ```json
    {
      "cpf": false,
      "cnpj": true,
      "cpf_valor": "undefined",
      "cnpj_valor": "07.140.525/0001-71"
    }
    ```
* **Atenção à regra de negócio:** No campo não aplicável, a string literal deve ser `"undefined"`.

---

### 2.13. `endereco`
* **Tipo:** `Dict[str, str]`
* **Chaves estritas:** `"nome da empresa"`, `"endereço"`, `"cep"`.
* **Origem no PDF:** Bloco cadastral do cliente/destinatário:
  - `"nome da empresa"`: Razão social ou nome do titular consumidor.
  - `"endereço"`: Logradouro, número, complemento e bairro.
  - `"cep"`: CEP do imóvel do cliente (no formato `XXXXX-XXX`), diferenciando do CEP da sede da concessionária Enel.

---

### 2.14. `CIP_ILUM_PUB_PREF_MUNICIPAL`
* **Tipo:** `float`
* **Origem no PDF:** Valor numérico do item `"CIP ILUM PUB PREF MUNICIPAL"` (Contribuição de Iluminação Pública). Caso ausente, `0.0`.

---

### 2.15. `juros_valor`
* **Tipo:** `float`
* **Origem no PDF:** Valor do item `"Juros Moratórios"` na coluna de valor. Centavos devem ser reconhecidos. Caso ausente, retornar `0.0`.

---

### 2.16. `multa_valor`
* **Tipo:** `float`
* **Origem no PDF:** Valor do item `"Multa"` na coluna de valor. Caso ausente, retornar `0.0`.

---

### 2.17. `bandeira_dados`
* **Tipo:** `Dict[str, float]`
* **Chaves:**
  - `"adic_band_comp"`: Valor do item de compensação (`Adic. Band. <Cor> Comp.`), preservando o sinal (ou `0.0` se não houver).
  - `"adicional_band"`: Valor do item de cobrança adicional (`Adicional Band. <Cor>`), positivo (ou `0.0` se não houver).
* **Exemplo:**
  ```json
  {
    "adic_band_comp": -29.07,
    "adicional_band": 34.37
  }
  ```

---

### 2.18. `lista_itens_fatura`
* **Tipo:** `List[Dict[str, Any]]`
* **Definição:** Lista completa de todos os itens faturados discriminados na tabela de itens da fatura.
* **Estrutura de cada item:**
  - `"nome_item"`: Nome integral do item tal como consta no documento.
  - `"valor"`: Valor financeiro positivo (`float`, em módulo).
  - `"valor_positivo"`: Booleano (`true` se for item a pagar / débito, `false` se for crédito / compensação com sinal negativo `-`).
* **Exemplo:**
  ```json
  [
    {
      "nome_item": "CIP ILUM PUB PREF MUNICIPAL",
      "valor": 65.09,
      "valor_positivo": true
    },
    {
      "nome_item": "Energia Consumida Faturada TE",
      "valor": 26.61,
      "valor_positivo": true
    },
    {
      "nome_item": "Adic. Band. Vermelha Comp.",
      "valor": 29.07,
      "valor_positivo": false
    },
    {
      "nome_item": "Energia Atv Inj TE oUC 08/2025 mPT GD2",
      "valor": 145.86,
      "valor_positivo": false
    }
  ]
  ```
