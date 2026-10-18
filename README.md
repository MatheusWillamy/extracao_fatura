# API de Extração de Faturas de Energia (Enel) - Docker & Easypanel

Microsserviço em Python (FastAPI) de alta performance para extração automatizada de dados de faturas de energia elétrica da Enel (Ceará/Brasil). 

Este serviço foi criado para **substituir o nó de Information Extractor do n8n** por uma solução:
- **Instantânea (<100ms)** vs 10-30s do LLM no n8n.
- **Zero custo de API** (parser estruturado determinístico em Python).
- **Sem alucinações**, mantendo estritamente 100% dos campos, tipos e regras de negócio.
- **Modo Híbrido com Fallback de IA**: Se necessário ou configurado, pode utilizar Gemini ou OpenRouter.
- **Pronto para Easypanel**: Contém `Dockerfile` e `docker-compose.yml` otimizados.

---

## 📁 Arquivos do Projeto

- [main.py](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/main.py): Servidor FastAPI com endpoints REST e Webhook compatíveis com o n8n.
- [extractor.py](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/extractor.py): Motor de extração estruturada e suporte a IA.
- [mockup_resposta.json](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/mockup_resposta.json): Mockup exato do retorno para a fatura de teste (`share-1792329128706-augusto-sergio-08.25.pdf`).
- [regras_extracao.md](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/regras_extracao.md): Manual com a regra de cada campo, origem e formato.
- [Dockerfile](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/Dockerfile): Imagem Docker enxuta baseada em `python:3.12-slim`.
- [docker-compose.yml](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/docker-compose.yml): Configuração Compose para Easypanel ou Docker local.
- [requirements.txt](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/requirements.txt): Dependências mínimas (`fastapi`, `pypdf`, etc.).
- [test_api.py](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/test_api.py): Suíte de testes automatizados com faturas reais.

---

## 🚀 Como Subir no Easypanel

### Método 1: Via Dockerfile / Git (Recomendado no Easypanel)
1. No seu Easypanel, crie um novo **Service** do tipo **App**.
2. Conecte o repositório Git onde estão estes arquivos.
3. Configure o **Build Type** como `Dockerfile`.
4. Defina o **Port** como `8000`.
5. *(Opcional)* Em **Environment Variables**, adicione se desejar usar IA como fallback:
   - `GEMINI_API_KEY`: Sua chave do Google Gemini (se quiser usar modelo `gemini-2.5-flash`).
   - `OPENROUTER_API_KEY`: Sua chave do OpenRouter (se preferir OpenRouter).
6. Clique em **Deploy**. O Easypanel fará o build e fornecerá um domínio público com HTTPS automático (ex: `https://fatura-api.seudominio.com`).

### Método 2: Via Docker Compose no Easypanel
1. Crie um novo **Project** -> **Service** -> **Docker Compose**.
2. Cole o conteúdo de [docker-compose.yml](file:///c:/Users/matheus_willamy/Documents/AboboraTech/AJDC/extração_fatura/docker-compose.yml).
3. Salve e clique em **Deploy**.

---

## 💻 Como Rodar Localmente

### Com Docker
```bash
docker compose up -d --build
```
A API estará disponível em `http://localhost:8000`. Acesse a documentação interativa em `http://localhost:8000/docs`.

### Sem Docker (Python Direto)
```bash
pip install -r requirements.txt
python main.py
```

---

## 🔗 Como Usar no n8n

No seu fluxo do n8n, você pode substituir o nó **Information Extractor** por um nó **HTTP Request**:

1. **Método:** `POST`
2. **URL:** `http://<seu-servidor-easypanel>:8000/homo_extracao_enel` (ou `/extract`)
3. **Send Body:** Ativado
4. **Body Content Type:** `Form-Data (Multipart)`
5. **Form Data Parameters:**
   - **Name:** `file`
   - **Parameter Type:** `n8n Binary File`
   - **Input Data Field Name:** `data` (ou o nome do campo binário no seu n8n)

> [!NOTE]
> **Compatibilidade Total**: A resposta da API já inclui o nó `{ "output": { ... } }` exatamente como o n8n LangChain Information Extractor gerava, além dos campos na raiz e do alias `cnpj_cpf`. Nenhum nó posterior do seu fluxo precisará ser alterado!

---

## 📡 Endpoints da API

### `POST /extract` ou `POST /homo_extracao_enel`
Endpoint principal de extração. Aceita:
- `multipart/form-data` com o campo `file`.
- Corpo binário `application/pdf`.
- JSON com `file_base64` ou `data`.

#### Parâmetros de Query:
- `mode`:
  - `auto` (padrão): Usa o parser estruturado ultra-rápido; caso a fatura não tenha itens e houver chave de IA configurada, recorre à IA.
  - `structured`: Força o extrator estruturado determinístico.
  - `ai`: Força extração via modelo de IA (requer chave configurada).
- `wrap_output`: `true` (padrão) para incluir `{ "output": { ... } }`.

#### Exemplo com cURL (Upload de Arquivo):
```bash
curl -X POST "http://localhost:8000/extract" \
  -F "file=@share-1792329128706-augusto-sergio-08.25.pdf"
```

#### Exemplo de Resposta:
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
      "nome_item": "Adicional Band. Vermelha",
      "valor": 34.37,
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
    },
    {
      "nome_item": "Energia Atv Inj TUSD oUC 08/2025 mPT GD2",
      "valor": 158.76,
      "valor_positivo": false
    }
  ],
  "output": { ... }
}
```

### `GET /health`
Verificação de integridade para monitoramento e healthchecks do Easypanel:
```json
{
  "status": "ok",
  "service": "api-extracao-fatura",
  "version": "1.1.0"
}
```
