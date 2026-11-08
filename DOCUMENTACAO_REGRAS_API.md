# Documentação Técnica Completa — API e Regras de Extração de Faturas

> **Escopo desta documentação:** Este documento descreve exatamente como a API ([`main.py`](file:///c:/Users/matheus_willamy/Documents/Github/extracao_fatura/main.py)) e o motor de extração ([`extractor.py`](file:///c:/Users/matheus_willamy/Documents/Github/extracao_fatura/extractor.py)) funcionam em produção — incluindo regras de cada campo, micro-análises de formação de datas/números, convenções de sinal (**positivo vs. negativo**), e exemplos reais do que o sistema **cobre** e do que **não cobre**.

---

## 1. Visão Geral da API

A API é construída em **FastAPI** (versão `1.1.0`) para extrair dados estruturados de faturas de energia elétrica (padrão **Enel Distribuição Ceará** / NF3e) visando compatibilidade com **n8n** e **FlutterFlow**.

### 1.1. Endpoints Disponíveis

| Método | Rota | Descrição | Retorno |
|---|---|---|---|
| `GET` | `/` | Metadados do serviço, versão e lista de rotas | `200 OK` (JSON) |
| `GET` | `/health` | Healthcheck para Docker/Easypanel (`status: "ok"`) | `200 OK` (JSON) |
| `POST` | `/extract` | Endpoint principal de extração | `200 OK` / `400` / `500` |
| `POST` | `/homo_extracao_enel` | Alias idêntico a `/extract` (compatibilidade webhook n8n) | `200 OK` / `400` / `500` |
| `POST` | `/webhook` | Alias idêntico a `/extract` | `200 OK` / `400` / `500` |

* **CORS:** Liberado para qualquer origem (`allow_origins=["*"]`, todos os métodos e headers).
* **Documentação Swagger nativa:** `/docs`.

### 1.2. Formas de Envio do PDF (`_get_pdf_bytes_from_request`)

A API processa a entrada na seguinte ordem de prioridade:

1. **`multipart/form-data`** com arquivo binário em qualquer um dos campos: `file`, `data` ou `attachment` (ordem: `file or data or attachment`).
2. **Corpo binário bruto** com `Content-Type` contendo `application/pdf` ou `application/octet-stream`.
3. **JSON (`application/json`) com Base64** em uma das chaves: `file_base64`, `data`, `file` ou `content`.
   * Se houver prefixo Data URI (ex.: `"data:application/pdf;base64,JVBERi0..."`), o parser divide na primeira vírgula (`split(",")[1]`) e decodifica o restante.
4. **Fallback bruto:** Se o corpo não tiver `Content-Type` esperado, mas começar com a assinatura `%PDF`, é aceito como PDF binário.

#### O que a entrada da API COBRE vs. NÃO COBRE

| Situação | Status | Comportamento |
|---|---|---|
| `multipart/form-data` com campo `file`, `data` ou `attachment` | **Coberto** | Extrai os bytes do PDF diretamente |
| `application/pdf` ou `application/octet-stream` no body | **Coberto** | Lê o body bruto como PDF |
| `application/json` com `file_base64` (com ou sem `data:...;base64,`) | **Coberto** | Decodifica Base64 |
| `multipart/form-data` com campo `pdf`, `arquivo` ou `documento` | **Não coberto** | Retorna `HTTP 400` (`Nenhum arquivo PDF encontrado`) |
| Envio de imagem (`PNG`, `JPG`) ou URL remota de PDF | **Não coberto** | Retorna `HTTP 400` ou erro de leitura do `pypdf` |
| Envio em lote (múltiplos PDFs no mesmo request) | **Não coberto** | Processa apenas o primeiro campo reconhecido |

### 1.3. Parâmetros de Execução (`mode`, `wrap_output`, `x-api-key`)

Os parâmetros `mode` e `wrap_output` podem ser enviados na **Query String** (ex.: `/extract?mode=structured&wrap_output=false`) ou dentro do **JSON Body** (quando `Content-Type` começa com `application/json`, sobrescrevendo os valores da query).

* **`mode`** (padrão: `"auto"`):
  * `"structured"`: Executa exclusivamente o parser determinístico Python (`parse_fatura_pdf`). Custo zero, execução em milissegundos, sem chamadas externas.
  * `"ai"`: Extrai o texto com `pypdf` e envia os primeiros **`12.000` caracteres** (`pdf_text[:12000]`) para LLM (`Gemini`, `OpenRouter` ou `OpenAI`).
  * `"auto"`: Executa `parse_fatura_pdf` primeiro. Só aciona fallback de IA se:
    1. `total_a_pagar == 0.0` **e** `len(lista_itens_fatura) == 0`; **ou**
    2. `parse_fatura_pdf` lançar exceção;
    **e** existir chave disponível em `x-api-key`, `GEMINI_API_KEY` ou `OPENROUTER_API_KEY`.
    * **Atenção:** No modo `"auto"`, a variável `OPENAI_API_KEY` sozinha **não** dispara o fallback automático (a verificação de fallback testa apenas `api_key`, `GEMINI_API_KEY` e `OPENROUTER_API_KEY`), embora `extract_fatura_with_ai` suporte `OPENAI_API_KEY` quando chamada em `mode="ai"`.
* **`wrap_output`** (padrão: `true`):
  * `true`: Retorna os campos na raiz **e** duplicados dentro de `"output": { ... }` (compatível tanto com acesso direto `$.total_a_pagar` quanto n8n `$.output.total_a_pagar`).
  * `false`: Retorna apenas os campos na raiz, sem a chave `"output"`.
* **Alias automático `cnpj_cpf` (`format_api_response`)**:
  * Além da chave canônica `"cnpj-cpf"` (com hífen), a API sempre injeta `"cnpj_cpf"` (com underscore) para compatibilidade com JSONPath do FlutterFlow.
* **Limitação de PDF escaneado (imagem sem texto):**
  * Como `extract_text_from_pdf` usa `pypdf` (extração de texto vetorial, sem OCR e sem envio de imagem/visão para o LLM), PDFs escaneados sem camada de texto resultam em texto vazio inclusive no modo `"ai"`.

---

## 2. Regras Globais e Micro-Análises Transversais

### 2.1. Micro-análise de Conversão Numérica (`_clean_number`)

Grande parte dos campos monetários passa por [`_clean_number`](file:///c:/Users/matheus_willamy/Documents/Github/extracao_fatura/extractor.py#L71-L84).

**Passo a passo da transformação:**

```text
Entrada PDF: "2.440,85-"
  1. strip()                        -> "2.440,85-"
  2. Detecta sinal (- início/fim)   -> is_neg = True
  3. Remove '-' e '.' (milhar)      -> "2440,85"
  4. Troca ',' por '.'              -> "2440.85"
  5. Converte para float            -> 2440.85
  6. Se n == 0.0 retorna 0.0; senão aplica -n -> -2440.85
```

* **O que cobre:**
  * Sinal negativo à direita (padrão contábil/Enel): `"142,88-"` -> `-142.88`
  * Sinal negativo à esquerda: `"-142,88"` -> `-142.88`
  * Milhares com ponto e decimais com vírgula: `"3.214,70-"` -> `-3214.7`
  * Zero negativo normalizado: `"0,00-"` -> `0.0` (nunca retorna `-0.0`)
* **O que não cobre:**
  * Números no padrão americano dentro de `_clean_number` (ex.: `"142.88"` teria o `.` removido como milhar e viraria `14288.0`).
  * Espaço entre sinal e número (ex.: `"- 142,88"` não casa nas regexes de captura).
  * Valores com símbolo `R$` embutido (a regex precisa consumir `R$` antes, como ocorre em `total_a_pagar`).

### 2.2. Regra Geral de Sinais (Positivo vs. Negativo)

| Grupo de Campos | Regra de Sinal | Detalhe |
|---|---|---|
| `lista_itens_fatura[*].valor` | **Preserva sinal (`+` ou `-`)** | Débito/zero: `valor >= 0` e `valor_positivo: true`. Crédito/desconto: `valor < 0` e `valor_positivo: false`. |
| `creditos_valor` | **Negativo** (soma com sinal) | Soma algébrica dos itens `TE` + `TUSD` injetados (ex.: `-304.62`, `-5986.62`). |
| `energia_atv_inj_TE_valor[*].valor` | **Preserva sinal (normalmente `-`)** | Ex.: `-145.86`. |
| `energia_atv_inj_TUSD_valor[*].valor` | **Preserva sinal (normalmente `-`)** | Ex.: `-158.76`. |
| `bandeira_dados.adic_band_comp` | **Preserva sinal (normalmente `-`)** | Ex.: `-29.07` (ou `0.0` se ausente). |
| `bandeira_dados.adicional_band` | **Preserva sinal (normalmente `+`)** | Ex.: `34.37` (ou `0.0` se ausente). |
| `bandeira_valor` | **Sempre positivo (`abs`)** | Módulo de `adic_band_comp` (ex.: `29.07`), ou `0` se não houver compensação. |
| `subtotal` e `total_a_pagar` | **Sempre positivo (`abs`)** | Usa `abs(...)` na extração. |
| `CIP_ILUM_PUB_PREF_MUNICIPAL`, `juros_valor`, `multa_valor` | **Preserva sinal na tabela / `abs` no fallback** | Na prática sempre positivos; se negativo na tabela, preserva sinal. |
| `creditos_utlizados[*].quantidade` | **Sempre não negativo (`>= 0`)** | Regex não captura `-`. |

---

## 3. Regras Detalhadas Campo a Campo (Micro-Análises + Cobre vs. Não Cobre)

### 3.1. `creditos_utlizados` *(atenção: grafia sem o segundo "i": `utlizados`)*

* **Tipo:** `List[Dict[str, Union[int, float, str]]]` (lista com 1 item)
* **Sinal:** Sempre `>= 0`
* **Origem e Regex:**
  ```python
  r"Saldo utilizado no m[eê]s:\s*([0-9.,]+)\s*([a-zA-Z]+)"  # re.IGNORECASE
  ```
* **Micro-análise de formação da `quantidade`:**
  1. Divide a string capturada pelos pontos (`parts = qtd_str.split('.')`).
  2. Se `len(parts) > 2` (2 ou mais pontos, padrão Enel como `"1.000.00"` ou `"1.660.20"`): concatena tudo antes do último ponto e mantém o último ponto como separador decimal (`"1000.00"` -> `1000`, `"1660.20"` -> `1660.2`).
  3. Se `len(parts) == 2` (1 ponto, ex.: `"453.26"`): mantém `qtd_str` como está.
  4. Se não houver ponto (`len(parts) == 1`): substitui `,` por `.`.
  5. Converte para `float`; se `val_float.is_integer()`, retorna `int` (`1000`), senão `round(val_float, 2)`.
  6. Se o campo não existir no PDF (ou falhar conversão): retorna `[{"quantidade": 0, "unidade": "kWh"}]`.
* **Exemplos do que COBRE:**
  * `"Saldo utilizado no mês: 453.26 kWh"` -> `[{"quantidade": 453.26, "unidade": "kWh"}]`
  * `"Saldo utilizado no mes: 1.000.00 kWh"` -> `[{"quantidade": 1000, "unidade": "kWh"}]`
  * `"Saldo utilizado no mês: 1.660.20 kWh"` -> `[{"quantidade": 1660.2, "unidade": "kWh"}]`
  * `"Saldo utilizado no mês: 7140,50 kWh"` -> `[{"quantidade": 7140.5, "unidade": "kWh"}]`
* **Exemplos do que NÃO COBRE:**
  * `"Saldo utilizado no mês: 1.000,50 kWh"` (1 ponto de milhar + vírgula): entra no ramo `len(parts) == 2`, `float("1.000,50")` falha e vira `0`!
  * `"Saldo utilizado no mês: 1.000 kWh"` (1 ponto de milhar sem decimais): `float("1.000")` vira `1` em vez de `1000`!
  * Textos diferentes de `"Saldo utilizado no mês:"` (ex.: `"Crédito utilizado:"`, `"Energia compensada:"`).
  * Múltiplos blocos de saldo utilizado no mesmo documento (captura apenas a primeira ocorrência).

---

### 3.2. `creditos_valor`

* **Tipo:** `float`
* **Sinal:** **Negativo** quando formado por compensações com `-` no PDF (ex.: `-304.62`, `-5986.62`). `0.0` se vazio.
* **Micro-análise:**
  * Soma todos os itens coletados em `energia_atv_inj_TE_valor` e `energia_atv_inj_TUSD_valor` e arredonda para 2 casas: `round(soma_te + soma_tusd, 2)`.
* **Exemplos do que COBRE:**
  * `[-142.88, -2440.85]` (TE) + `[-188.19, -3214.70]` (TUSD) -> `-5986.62`.
  * Múltiplos meses anteriores acumulados na mesma fatura (ex.: `10/2024` + `11/2024`).
* **Exemplos do que NÃO COBRE:**
  * Créditos de bandeira (`Adic. Band. Vermelha Comp.`: `-29.07` **não** é somado em `creditos_valor`).
  * Créditos de energia injetada cuja descrição não contenha exatamente `"Energia Atv Inj TE oUC"` ou `"Energia Atv Inj TUSD oUC"` (case-sensitive) ou sem data `MM/AAAA`.

---

### 3.3. `energia_atv_inj_TE_valor` e `energia_atv_inj_TUSD_valor`

* **Tipo:** `List[Dict[str, Union[int, float]]]` (`{"mes": int, "ano": int, "valor": float}`)
* **Sinal:** **Preserva o sinal do PDF** (normalmente **negativo**, ex.: `-145.86`, `-158.76`).
* **Micro-análise de formação de `mes`, `ano` e `valor`:**
  1. A linha precisa primeiro casar com o padrão de item `kWh` na tabela (`Itens de Fatura` até `Subtotal Faturamento`):
     ```python
     r"^(.*?)\s+kWh\s+(-?[0-9.,]+-?)\s+(-?[0-9.,]+-?)\s+(-?[0-9.,]+-?)"
     ```
  2. Verifica substring exata (**case-sensitive**):
     * `"Energia Atv Inj TE oUC"` -> vai para `energia_atv_inj_TE_valor`
     * `"Energia Atv Inj TUSD oUC"` -> vai para `energia_atv_inj_TUSD_valor`
  3. Extrai mês e ano de `nome_item` com `r"(\d{2})/(\d{4})"`:
     * `mes = int(group(1))` (converte `"08"` -> `8`, `"10"` -> `10`)
     * `ano = int(group(2))` (converte `"2025"` -> `2025`)
  4. `valor`: resultado de `round(_clean_number(valor_raw), 2)`.
* **Exemplos do que COBRE:**
  * `Energia Atv Inj TE oUC 08/2025 mPT GD2 kWh 453 0,32199- 145,86- ...` -> `{"mes": 8, "ano": 2025, "valor": -145.86}`
  * `Energia Atv Inj TUSD oUC 10/2024 mPT kWh 394 0,47655- 188,19- ...` -> `{"mes": 10, "ano": 2024, "valor": -188.19}`
  * Múltiplos meses na mesma fatura (`10/2024` e `11/2024` geram lista com 2 objetos).
* **Exemplos do que NÃO COBRE:**
  * Mês/ano com 2 dígitos de ano (`08/25`) ou mês de 1 dígito (`8/2025`).
  * Sigla diferente de `oUC` (ex.: `mUC`, `TE GD`, ou caixa alta `ENERGIA ATV INJ TE OUC`).
  * Item de injeção sem data `MM/AAAA` no nome (entra em `lista_itens_fatura`, mas é ignorado em `energia_atv_inj_*`).
  * Linhas com unidade diferente de `kWh` (ex.: `kW`).

---

### 3.4. `bandeira`

* **Tipo:** `str` (primeira letra maiúscula via `.capitalize()`)
* **Sinal:** N/A (texto)
* **Micro-análise de prioridade (4 etapas):**
  1. Cor extraída diretamente das linhas da tabela de itens: `Adic. Band. <Cor> Comp.` ou `Adicional Band. <Cor>`.
  2. Regex no texto completo: `r"Band(?:eira)?\.?\s*Tarif\.?:\s*([A-Za-z]+)"` (ex.: `"Band. Tarif.: Vermelha"` -> `"Vermelha"`).
  3. Regex no texto completo: `r"Bandeira\s+([A-Za-z]+)"`.
  4. Busca literal no texto minúsculo na ordem: `"amarela"` -> `"Amarela"`, `"vermelha"` -> `"Vermelha"`, `"verde"` -> `"Verde"`, ou fallback final `"Verde"`.
* **Exemplos do que COBRE:**
  * `"Períodos: Band. Tarif.: Vermelha : 04/07 - 04/08"` -> `"Vermelha"`
  * Item `"Adic. Band. Amarela Comp."` -> `"Amarela"`
  * Fatura sem cobrança de bandeira -> `"Verde"`
* **Exemplos do que NÃO COBRE:**
  * Diferenciar `"Vermelha Patamar 1"` de `"Vermelha Patamar 2"` (retorna sempre apenas `"Vermelha"`).
  * Bandeira com nome composto (ex.: `"Escassez Hídrica"` capturaria apenas `"Escassez"` no nível 2/3 ou `"Verde"` no nível 4).

---

### 3.5. `bandeira_valor` e `bandeira_dados`

* **Tipos:**
  * `bandeira_valor`: `float` ou `int` (`0` quando ausente)
  * `bandeira_dados`: `{"adic_band_comp": float, "adicional_band": float}`
* **Regras de Sinal:**
  * `bandeira_valor`: **Sempre positivo (`abs(adic_band_comp_val)`)** se `adic_band_comp_val != 0.0`, senão `0`.
  * `bandeira_dados.adic_band_comp`: **Preserva o sinal** (normalmente **negativo**, ex.: `-29.07`, `-17.07`).
  * `bandeira_dados.adicional_band`: **Preserva o sinal** (normalmente **positivo**, ex.: `34.37`, `20.71`).
* **Exemplos do que COBRE:**
  * Fatura com `"Adicional Band. Vermelha"` (`34,37`) e `"Adic. Band. Vermelha Comp."` (`29,07-`):
    * `bandeira_valor`: `29.07`
    * `bandeira_dados`: `{"adic_band_comp": -29.07, "adicional_band": 34.37}`
  * Fatura Bandeira Verde (sem linhas de adicional): `bandeira_valor: 0`, `bandeira_dados: {"adic_band_comp": 0.0, "adicional_band": 0.0}`.
* **Exemplos do que NÃO COBRE:**
  * Fatura **sem compensação** (`Adic. Band. ... Comp.` ausente), mas **com cobrança** (`Adicional Band. Amarela` `20,71`): `bandeira_dados.adicional_band` será `20.71`, porém `bandeira_valor` retornará `0` (pois segue estritamente a regra de ler o campo `Comp.`).
  * Múltiplos itens de bandeira por competências diferentes (mantém o último valor lido, não soma).

---

### 3.6. `data_vencimento`

* **Tipo:** `str` (formato ISO `AAAA-MM-DD`, ou `""` se não encontrado)
* **Sinal:** N/A
* **Micro-análise de formação Dia / Mês / Ano:**
  1. Prioridade 1 (boleto/canhoto):
     ```python
     r"Data Vencimento:\s*(\d{2})/(\d{2})/(\d{4})"  # re.IGNORECASE
     ```
     Aceita quebra de linha entre o rótulo e a data (ex.: `"Data Vencimento:\n14/08/2025"`).
  2. Prioridade 2 (cabeçalho superior):
     ```python
     r"\d{2}/\d{4}\s+(\d{2})/(\d{2})/(\d{4})\s+R\$\s*[0-9.,]+"
     ```
     Casa linhas no estilo `"08/2025 14/08/2025 R$ 265,29"`.
  3. Remonta grupos `(d, m, y)` como `f"{y}-{m}-{d}"`.
* **Exemplos do que COBRE:**
  * `"Data Vencimento:\n14/08/2025"` -> `"2025-08-14"`
  * `"08/2025 14/08/2025 R$ 265,29"` -> `"2025-08-14"`
* **Exemplos do que NÃO COBRE:**
  * Rótulos alternativos sem fallback correspondente (ex.: `"Vencimento: 14/08/2025"` sem a palavra `"Data"` e sem linha `MM/AAAA DD/MM/AAAA R$ ...`).
  * Ano com 2 dígitos (`14/08/25`) ou data por extenso (`14 de agosto de 2025`).

---

### 3.7. `subtotal` e `total_a_pagar`

* **Tipo:** `float`
* **Sinal:** **Sempre positivo (`abs`)**; padrão `0.0`.
* **Micro-análise de `subtotal`:**
  * Varre todas as linhas com `r"Subtotal\s+[A-Za-zÀ-ÿ]+\s+([0-9.,]+)"` (case-insensitive) e soma todos os valores encontrados (`round(sum(subtotais), 2)`).
  * Se `subtotal == 0.0` e `total_a_pagar != 0.0`, assume `subtotal = total_a_pagar`.
* **Micro-análise de `total_a_pagar`:**
  1. Prioridade 1: `r"Valor do Documento:\s*R\$\s*([0-9.,]+)"` (boleto).
  2. Prioridade 2: `r"\bTOTAL\s*\n\s*([0-9.,]+)"` (valor na linha logo abaixo de `TOTAL`).
* **Exemplos do que COBRE:**
  * `Subtotal Faturamento 200,20` + `Subtotal Outros 65,09` -> `subtotal: 265.29`
  * `Subtotal Faturamento 879,46` + `Subtotal Outros 339,57` -> `subtotal: 1219.03`
  * `Valor do Documento:\nR$ 265,29` -> `total_a_pagar: 265.29`
* **Exemplos do que NÃO COBRE:**
  * `Subtotal` composto por duas ou mais palavras antes do número (ex.: `"Subtotal de Serviços 50,00"` não casa com `\s+[A-Za-zÀ-ÿ]+\s+`).
  * Faturas sem canhoto `"Valor do Documento: R$ ..."` onde o valor numérico apareça na linha **anterior** ou na **mesma linha** da palavra `TOTAL` (ex.: `TOTAL R$ 265,29`).
  * Fatura com total negativo (crédito acumulado) ou texto `"ISENTO"`/`"SEM VALOR A PAGAR"`.

---

### 3.8. `leitura_anterior`, `leitura_atual` e `tipo_ligacao_eletrica`

* **Tipos:**
  * `leitura_anterior`: `str` (`"AAAA-MM-DDT00:00:00-03:00"` ou `""`)
  * `leitura_atual`: `str` (`"AAAA-MM-DDT00:00:00-03:00"` ou `""`)
  * `tipo_ligacao_eletrica`: `str` (`"TRIFÁSICO"`, `"MONOFÁSICO"`, `"BIFÁSICO"` em maiúsculas ou `""`)
* **Sinal:** N/A
* **Micro-análise conjunta de Dia / Mês / Ano / Fuso e Tipo de Ligação:**
  ```python
  r"(TRIF[AÁ]SICO|MONOF[AÁ]SICO|BIF[AÁ]SICO)\s+(\d{2})/(\d{2})/(\d{4})\s+(\d{2})/(\d{2})/(\d{4})"
  ```
  * Em faturas Enel, a extração de texto gera uma linha como:
    `Residencial TRIFÁSICO 03/07/2025 04/08/2025 32 03/09/2025`
  * Grupo 1 -> `tipo_ligacao_eletrica` (`.upper()`)
  * Grupos 2, 3, 4 (`03/07/2025`) -> `leitura_anterior = "2025-07-03T00:00:00-03:00"`
  * Grupos 5, 6, 7 (`04/08/2025`) -> `leitura_atual = "2025-08-04T00:00:00-03:00"`
  * A hora `00:00:00` e o fuso `-03:00` são fixos. A data da próxima leitura (`03/09/2025`) é ignorada.
* **Exemplos do que COBRE:**
  * `"Residencial TRIFÁSICO 03/07/2025 04/08/2025 32 03/09/2025"` -> `TRIFÁSICO`, `2025-07-03T00:00:00-03:00`, `2025-08-04T00:00:00-03:00`
  * `"COMERCIAL BIFASICO 01/01/2025 02/02/2025"` -> `BIFASICO` (preserva sem acento se o PDF estiver sem acento)
* **Exemplos do que NÃO COBRE:**
  * Se o tipo de ligação não estiver imediatamente colado às duas datas (ex.: número de instalação ou texto no meio, ou tipo `"BIFÁSICO 2 FIOS"`), **todos os 3 campos ficam `""`** (não existe fallback buscando na tabela `EQUIPAMENTOS DE MEDIÇÃO`).
  * Fuso horário diferente de `-03:00` (ex.: Acre `-05:00`, Manaus `-04:00`).

---

### 3.9. `cnpj-cpf` (e alias `cnpj_cpf`)

* **Tipo:** `Dict[str, Union[bool, str]]`
* **Estrutura:** `{"cpf": bool, "cnpj": bool, "cpf_valor": str, "cnpj_valor": str}`
* **Micro-análise:**
  1. Procura primeiro dentro do bloco cadastral (entre a linha `TRIFÁSICO/MONOFÁSICO/BIFÁSICO DD/MM/AAAA` e até 6 linhas seguintes) por `r"CPF/CNPJ:\s*([0-9.\-\/]+)"`.
  2. Se não encontrar, aplica fallback no documento inteiro (`full_text`).
  3. Remove tudo que não for dígito (`re.sub(r"\D", "", doc_str)`) e decide pelo tamanho:
     * `len(digits) == 11`: `cpf=True`, `cnpj=False`, `cpf_valor=doc_str`, `cnpj_valor="undefined"`
     * `len(digits) == 14`: `cpf=False`, `cnpj=True`, `cpf_valor="undefined"`, `cnpj_valor=doc_str`
     * Outro tamanho / ausente: `cpf=False`, `cnpj=False`, `cpf_valor="undefined"`, `cnpj_valor="undefined"`
  4. `format_api_response` garante também a chave `"cnpj_cpf"` com o mesmo objeto.
* **Exemplos do que COBRE:**
  * `"CPF/CNPJ: 105.432.952-49"` -> `cpf: true`, `cpf_valor: "105.432.952-49"`, `cnpj_valor: "undefined"`
  * `"CPF/CNPJ: 07.140.525/0001-71"` -> `cnpj: true`, `cpf_valor: "undefined"`, `cnpj_valor: "07.140.525/0001-71"`
  * `"CPF/CNPJ: 10543295249"` -> reconhecido normalmente pelos 11 dígitos.
* **Exemplos do que NÃO COBRE:**
  * Documento mascarado com asteriscos/letras (ex.: `"***.432.952-**"` tem menos de 11 dígitos numéricos -> ambos ficam `"undefined"`).
  * Rótulo apenas `"CNPJ:"` ou `"CPF:"` (a regex exige literalmente `"CPF/CNPJ:"`; no cabeçalho da Enel existe `"CNPJ: 07.047.251/0001-70"` da própria distribuidora, que é ignorado justamente por não ser `"CPF/CNPJ:"`).

---

### 3.10. `endereco`

* **Tipo:** `Dict[str, str]` (`{"nome da empresa": str, "endereço": str, "cep": str}`)
* **Micro-análise:**
  1. Localiza a linha âncora `(TRIF[AÁ]SICO|MONOF[AÁ]SICO|BIF[AÁ]SICO)\s+\d{2}/\d{2}/\d{4}`.
  2. `nome da empresa` = linha imediatamente seguinte (`lines[i+1]`).
  3. Varre `lines[i+2]` até `lines[i+7]`:
     * Se contiver `"CPF/CNPJ:"`, encerra o bloco de endereço.
     * Se contiver `"CEP:"`, extrai `r"CEP:\s*(\d{5}-\d{3})"`.
     * Caso contrário, concatena com espaço em `"endereço"`.
  4. **Fallback global de CEP:** Se não encontrou CEP no bloco, busca todos `CEP:\s*(\d{5}-\d{3})` do PDF e **descarta `"60135-040"`** (CEP da sede da Enel Ceará), pegando o primeiro restante (ou o último da lista).
* **Exemplos do que COBRE:**
  * Bloco padrão Enel Ceará:
    ```text
    Residencial TRIFÁSICO 03/07/2025 04/08/2025 32 03/09/2025
    AUGUSTO SERGIO FARIA DE MESQUITA
    RU MARCOS MACEDO 00843 AP 1101
    ALDEOTA FORTALEZA CE
    CEP: 60150-190
    CPF/CNPJ: 105.432.952-49 ...
    ```
    Resulta em: `"nome da empresa": "AUGUSTO SERGIO FARIA DE MESQUITA"`, `"endereço": "RU MARCOS MACEDO 00843 AP 1101 ALDEOTA FORTALEZA CE"`, `"cep": "60150-190"`.
* **Exemplos do que NÃO COBRE:**
  * Nome da empresa quebrado em 2 linhas (a segunda linha entra dentro de `"endereço"`).
  * Bloco de endereço com mais de 5 linhas entre o nome e `CPF/CNPJ:`.
  * CEP sem hífen (`60150190`).
  * Outra distribuidora em fallback global: o filtro de exclusão conhece apenas o CEP da Enel CE (`60135-040`).

---

### 3.11. `CIP_ILUM_PUB_PREF_MUNICIPAL`, `juros_valor` e `multa_valor`

* **Tipo:** `float` (padrão `0.0`)
* **Sinal:**
  * Dentro da tabela (`Itens de Fatura` .. `Subtotal Faturamento`): captura `(-?[0-9.,]+-?)` e preserva o sinal (na prática quase sempre positivos).
  * No fallback global (`full_text`, acionado se continuar `0.0`): captura `([0-9.,]+)` e aplica `abs(...)`.
* **Regexes exatas:**
  * `CIP_ILUM_PUB_PREF_MUNICIPAL`: `r"CIP ILUM PUB PREF MUNICIPAL\s+(-?[0-9.,]+-?)"`
  * `juros_valor`: `r"Juros Morat[oó]rios\s+(-?[0-9.,]+-?)"`
  * `multa_valor`: `r"^Multa\s+(-?[0-9.,]+-?)"` na tabela; `r"\bMulta\s+([0-9.,]+)"` no fallback global.
* **Exemplos do que COBRE:**
  * `"CIP ILUM PUB PREF MUNICIPAL 65,09 0,00 ..."` -> `65.09`
  * `"Juros Moratórios 0,45 0,00 ..."` -> `0.45`
  * `"Multa 6,70 0,00 ..."` -> `6.7`
  * `"CIP ILUM PUB PREF MUNICIPAL 10,50-"` -> `-10.5` (na tabela)
* **Exemplos do que NÃO COBRE:**
  * Nomenclaturas diferentes como `"COSIP"`, `"Contrib. Ilum. Pública"`, `"Juros de Mora"`, `"Multa Moratória"`, `"Encargos"`.
  * Texto intercalado antes do valor (ex.: `"Multa Ref. 04/2025 6,70"`).
  * Múltiplas linhas do mesmo item (sobrescreve com a última, não acumula).

---

### 3.12. `lista_itens_fatura`

* **Tipo:** `List[Dict[str, Any]]` (`{"nome_item": str, "valor": float, "valor_positivo": bool}`)
* **Regra definitiva de Sinal (Negativo vs. Positivo):**
  * **Item positivo ou zero (`valor >= 0`):** `"valor"` positivo (ex.: `2594.6`, `65.09`, `0.0`) e `"valor_positivo": true`.
  * **Item negativo (`valor < 0`):** `"valor"` **negativo** (ex.: `-142.88`, `-2440.85`, `-29.07`) e `"valor_positivo": false`.
  * **Invariante garantida em código:** `item["valor_positivo"] == (item["valor"] >= 0)` e normalização de `-0.0` para `0.0`.
  * **Propriedade matemática:** Em faturas padrão onde todos os itens lançados estão na janela, `round(sum(i["valor"] for i in lista_itens_fatura), 2) == total_a_pagar` (ex.: `265.29` na fatura `augusto-sergio` e `1219.03` na fatura `RENAISSANCE MICHELANGELO 01.25`).
* **Micro-análise de extração da tabela:**
  1. **Janela da tabela:** Inicia na linha com `"itens de fatura"` (case-insensitive) e termina na primeira linha seguinte com `"subtotal faturamento"` (case-insensitive).
  2. **Filtro de cabeçalho:** Ignora linhas contendo qualquer uma das substrings: `"com tributos"`, `"valor (r$)"`, `"pis/cofins"`, `"base calc"`, `"icms"`, `"alíquota"`, `"tarifa"`, `"unit (r$)"`.
  3. **Padrões reconhecidos dentro da janela:**
     * `CIP ILUM PUB PREF MUNICIPAL <valor>`
     * `Juros Moratórios <valor>`
     * `^Multa <valor>`
     * `^(.*?)\s+kWh\s+(-?[0-9.,]+-?)\s+(-?[0-9.,]+-?)\s+(-?[0-9.,]+-?)` (captura `nome_item` no grupo 1 e `valor` no grupo 4, após unidade `kWh`, quantidade e preço unitário).
* **Exemplos do que COBRE:**
  * `"Energia Ativa Fornecida TE kWh 7.170 0,36187 2.594,60 ..."` -> `{"nome_item": "Energia Ativa Fornecida TE", "valor": 2594.6, "valor_positivo": true}`
  * `"Energia Atv Inj TE oUC 10/2024 mPT kWh 394 0,36181- 142,88- ..."` -> `{"nome_item": "Energia Atv Inj TE oUC 10/2024 mPT", "valor": -142.88, "valor_positivo": false}`
  * `"Energia Atv Inj TUSD oUC 11/2024 mPT kWh 6.745 0,47660- 3.214,70- ..."` -> `{"nome_item": "Energia Atv Inj TUSD oUC 11/2024 mPT", "valor": -3214.7, "valor_positivo": false}`
  * `"Adic. Band. Vermelha Comp. kWh 453 0,06417- 29,07- ..."` -> `{"nome_item": "Adic. Band. Vermelha Comp.", "valor": -29.07, "valor_positivo": false}`
  * `"CIP ILUM PUB PREF MUNICIPAL 339,57 ..."` -> `{"nome_item": "CIP ILUM PUB PREF MUNICIPAL", "valor": 339.57, "valor_positivo": true}`
  * `"Juros Moratórios 0,45 ..."` e `"Multa 6,70 ..."` -> `valor_positivo: true`
  * Sinal à esquerda (`-50,00`) e `CIP`/`Juros`/`Multa` negativos (`10,50-`, `-1,25`, `2,30-`).
* **Exemplos do que NÃO COBRE:**
  * **Lançamentos diversos sem `kWh`** diferentes de `CIP ILUM PUB PREF MUNICIPAL`, `Juros Moratórios` e `Multa` — por exemplo, `"DOACAO ART CIDADA JUAZEIRO 85 99191 1643 2,00"` (observado na fatura real `Sociedada beneficente praia 04.25.pdf`), parcelamentos, taxas de religação, serviços de terceiros, descontos sem `kWh`.
  * **Unidades diferentes de `kWh`** (ex.: demanda `kW`, energia reativa `kVArh` em grupo A).
  * **Itens listados após `"Subtotal Faturamento"`** (não entram na janela `start_idx .. end_idx`).
  * **Itens com alguma palavra reservada do filtro de cabeçalho** no nome (ex.: um item cujo nome contenha `"tarifa"` ou `"icms"` seria descartado como se fosse cabeçalho).
  * **Nome do item quebrado em duas linhas** antes de `kWh` (perde a parte da linha anterior).

---

## 4. Exemplos Completos de Entrada x Saída Real

### Exemplo A — Fatura com Múltiplos Créditos de Meses Anteriores (`ENEL RENAISSANCE MICHELANGELO 01.25.pdf`)

**Trecho bruto da tabela extraído pelo `pypdf`:**
```text
Energia Ativa Fornecida TE kWh 7.170 0,36187 2.594,60 118,92 2.594,60 20,00% 518,92 0,27291
Energia Ativa Fornecida TUSD kWh 7.170 0,59574 4.271,48 195,79 4.271,48 20,00% 854,29 0,44929
Energia Atv Inj TE oUC 10/2024 mPT kWh 394 0,36181- 142,88- 6,54- 142,88- 20,00% 28,57- 0,27291
Energia Atv Inj TE oUC 11/2024 mPT kWh 6.745 0,36187- 2.440,85- 111,88- 2.440,85- 20,00% 488,17- 0,27291
Energia Atv Inj TUSD oUC 10/2024 mPT kWh 394 0,47655- 188,19- 10,77- 0,00 0,00% 0,00 0,44929
Energia Atv Inj TUSD oUC 11/2024 mPT kWh 6.745 0,47660- 3.214,70- 184,20- 0,00 0,00% 0,00 0,44929
CIP ILUM PUB PREF MUNICIPAL 339,57 0,00 0,00 0,00% 0,00
Subtotal Faturamento 879,46
Subtotal Outros 339,57
```

**Trecho da saída JSON gerada:**
```json
{
  "creditos_valor": -5986.62,
  "energia_atv_inj_TE_valor": [
    { "mes": 10, "ano": 2024, "valor": -142.88 },
    { "mes": 11, "ano": 2024, "valor": -2440.85 }
  ],
  "energia_atv_inj_TUSD_valor": [
    { "mes": 10, "ano": 2024, "valor": -188.19 },
    { "mes": 11, "ano": 2024, "valor": -3214.7 }
  ],
  "subtotal": 1219.03,
  "total_a_pagar": 1219.03,
  "lista_itens_fatura": [
    { "nome_item": "Energia Ativa Fornecida TE", "valor": 2594.6, "valor_positivo": true },
    { "nome_item": "Energia Ativa Fornecida TUSD", "valor": 4271.48, "valor_positivo": true },
    { "nome_item": "Energia Atv Inj TE oUC 10/2024 mPT", "valor": -142.88, "valor_positivo": false },
    { "nome_item": "Energia Atv Inj TE oUC 11/2024 mPT", "valor": -2440.85, "valor_positivo": false },
    { "nome_item": "Energia Atv Inj TUSD oUC 10/2024 mPT", "valor": -188.19, "valor_positivo": false },
    { "nome_item": "Energia Atv Inj TUSD oUC 11/2024 mPT", "valor": -3214.7, "valor_positivo": false },
    { "nome_item": "CIP ILUM PUB PREF MUNICIPAL", "valor": 339.57, "valor_positivo": true }
  ]
}
```
> *Conferência:* `2594.6 + 4271.48 - 142.88 - 2440.85 - 188.19 - 3214.7 + 339.57 = 1219.03` (`total_a_pagar`). E `-142.88 - 2440.85 - 188.19 - 3214.7 = -5986.62` (`creditos_valor`).

### Exemplo B — Caso real onde um item NÃO entra em `lista_itens_fatura` (`Sociedada beneficente praia 04.25.pdf`)

**Trecho bruto extraído pelo `pypdf`:**
```text
CIP ILUM PUB PREF MUNICIPAL 307,83 0,00 0,00 0,00% 0,00
DOACAO ART CIDADA JUAZEIRO 85 99191
1643
2,00 0,00 0,00 0,00% 0,00
Juros Moratórios 0,08 0,00 0,00 0,00% 0,00
Multa 4,85 0,00 0,00 0,00% 0,00
Subtotal Faturamento 287,89
Subtotal Outros 314,76
```
* **Resultado:** `CIP ILUM PUB PREF MUNICIPAL` (`307.83`), `Juros Moratórios` (`0.08`) e `Multa` (`4.85`) são extraídos, porém `"DOACAO ART CIDADA JUAZEIRO..."` (`2,00`) **não é capturado** em `lista_itens_fatura` (porque não tem `kWh` nem casa com `CIP`/`Juros`/`Multa`), embora seu valor componha `Subtotal Outros` (`307,83 + 2,00 + 0,08 + 4,85 = 314,76`) e `subtotal`/`total_a_pagar` (`602.65`).

