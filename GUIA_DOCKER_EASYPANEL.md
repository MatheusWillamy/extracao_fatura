# Guia Definitivo: Padrão de Containerização e Execução de APIs no Docker & Easypanel

Este documento consolida toda a arquitetura, decisões técnicas, configurações de rede e lições aprendidas durante o setup da API em Docker, servindo como **blueprint (gabarito) reutilizável** para qualquer nova API ou microsserviço que precise seguir o mesmo estilo de execução.

---

## 🎯 1. Visão Geral da Arquitetura

O padrão adotado entrega:
- **Build enxuto e ultrarrápido**: Imagem base `python:3.12-slim` com peso reduzido (~150MB).
- **Otimização de Cache em Camadas (Layer Caching)**: Dependências só são reinstaladas quando o `requirements.txt` sofrer alterações, tornando builds subsequentes de código quase instantâneos (< 2 segundos).
- **Logs em Tempo Real**: `PYTHONUNBUFFERED=1` para evitar acúmulo de buffer de stdout/stderr, garantindo visibilidade imediata nos logs do Docker e Easypanel.
- **Healthcheck Nativo Zero-Dependency**: Verificação de integridade usando a biblioteca padrão do Python (`urllib.request`), dispensando `curl` ou `wget` no sistema operacional.
- **Roteamento Interno no Easypanel (Traefik)**: Configuração de rede externa `easypanel` e nomes fixos de serviço/contêiner para comunicação direta inter-serviços (ex: n8n falando com a API via DNS interno `http://eleveit01_extracao_fatura:8000`).
- **Compatibilidade n8n / Webhooks**: Endpoints que aceitam múltiplos formatos de payload (`multipart/form-data`, binário puro `application/pdf` e JSON com `base64`) e retornam a chave `{ "output": { ... } }`.

---

## 🏗️ 2. Arquivos de Configuração do Padrão

### 📄 2.1 `.dockerignore`
O `.dockerignore` impede que arquivos locais desnecessários ou sensíveis sejam enviados para o contexto de build do Docker, mantendo a imagem leve e prevenindo conflitos de ambiente.

```dockerignore
__pycache__
*.pyc
*.pyo
*.pyd
.Python
env/
venv/
.venv
.env
.git
.gitignore
*.pdf
scratch/
tests/
```

---

### 🐳 2.2 `Dockerfile` Otimizado
O `Dockerfile` segue estritamente a ordem de camadas para tirar o máximo proveito do cache do Docker.

```dockerfile
FROM python:3.12-slim

# 1. Impede a escrita de arquivos .pyc e força flush imediato de logs (stdout/stderr)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# 2. Copia e instala apenas requirements primeiro (Camada com Cache isolado)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copia o código da aplicação
COPY extractor.py /app/extractor.py
COPY main.py /app/main.py

# 4. Declara a porta exposta
EXPOSE 8000

# 5. Healthcheck nativo em Python (dispensa curl/wget no slim)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 6. Inicialização do Uvicorn escutando em 0.0.0.0 (obrigatório em contêineres)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

> [!IMPORTANT]
> **Host 0.0.0.0 vs 127.0.0.1**: Dentro de um contêiner Docker, o servidor DEVE obrigatoriamente escutar em `0.0.0.0`. Se escutar em `127.0.0.1`, a porta não responderá a requisições externas ao contêiner, mesmo com `ports` mapeadas.

---

### 📦 2.3 `docker-compose.yml` (Padrão Easypanel + Local)
Ajustado com suporte a rede externa do Easypanel e publicação de portas:

```yaml
services:
  eleveit01_extracao_fatura:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: eleveit01_extracao_fatura
    restart: unless-stopped
    ports:
      - "8000:8000"
    expose:
      - "8000"
    environment:
      - PORT=8000
      # Variáveis de ambiente opcionais / Chaves de API
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
      - GEMINI_MODEL=gemini-2.5-flash
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - default
      - easypanel

networks:
  easypanel:
    external: true
```

#### 🔍 Por que essa configuração de rede e container_name é crucial?
1. **`container_name: eleveit01_extracao_fatura`**: 
   No Easypanel e no Docker Swarm, o Traefik e os outros serviços usam o DNS interno baseado no nome do container/serviço. Definir explicitamente o nome previne que o Compose gere nomes aleatórios como `extracao_fatura_eleveit01_extracao_fatura_1`.
2. **`networks: [default, easypanel]` + `easypanel: external: true`**:
   - O Easypanel gerencia os domínios e certificados SSL via Traefik conectado na rede Docker bridge `easypanel`.
   - Se o contêiner não estiver na rede `easypanel`, o Traefik não consegue repassar o tráfego HTTP/HTTPS do seu domínio para a porta 8000.
   - Além disso, permite que outros contêineres na mesma VPS (ex: um n8n auto-hospedado) façam requisições internas diretamente para `http://eleveit01_extracao_fatura:8000` com latência zero e sem sair para a internet pública.

---

## ⚡ 3. Padrão no Código Python (`main.py`)

Para que o contêiner funcione perfeitamente com Easypanel, n8n e frontends (FlutterFlow, React, etc.), o código da API deve contemplar:

### 3.1 Endpoint `/health` Dedicado
```python
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "api-extracao-fatura",
        "version": "1.1.0"
    }
```

### 3.2 CORS Completo Ativado
Permite que navegadores e frontends consumam a API sem bloqueios de política de mesma origem:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3.3 Resiliência na Recepção de Payloads (Multipart, Binary e Base64)
Um dos maiores problemas em automações (n8n, Make, FlutterFlow) é a variação no nome do campo do arquivo (`file`, `data`, `attachment`) ou envio como corpo binário puro.

O extrator inteligente trata todos esses casos:
```python
@app.post("/extract")
@app.post("/homo_extracao_enel")
async def extract_invoice_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    data: Optional[UploadFile] = File(None),
    attachment: Optional[UploadFile] = File(None),
    ...
):
    uploaded_file = file or data or attachment
    pdf_bytes = await _get_pdf_bytes_from_request(request, uploaded_file)
    ...
```

E a função extratora faz o fallback automático:
1. Multipart upload (`file`, `data`, `attachment`).
2. `Content-Type: application/pdf` ou `application/octet-stream` com corpo cru (`request.body()`).
3. JSON com campos `file_base64`, `data`, `file` ou `content`.
4. Verificação de assinatura binária de arquivo (`raw_body.startswith(b"%PDF")`).

---

## 📋 4. Checklist para Replicar em Outra API

Ao criar um novo microsserviço ou API para rodar no mesmo estilo:

### Passo 1: Estrutura de Arquivos
Crie a raiz do seu novo projeto com:
```
meu-novo-servico/
├── .dockerignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── main.py
└── README.md
```

### Passo 2: Configurar o `requirements.txt`
Coloque as dependências com versões mínimas:
```txt
fastapi>=0.110.0
uvicorn>=0.28.0
pydantic>=2.0.0
python-multipart>=0.0.9
httpx>=0.27.0
```

### Passo 3: Ajustar o `docker-compose.yml`
Substitua os nomes de serviço e container:
```yaml
services:
  meu_novo_servico:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: meu_novo_servico
    restart: unless-stopped
    ports:
      - "8001:8000"   # Se rodar localmente e a 8000 estiver ocupada, use 8001
    expose:
      - "8000"
    environment:
      - PORT=8000
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - default
      - easypanel

networks:
  easypanel:
    external: true
```

### Passo 4: Como Rodar e Testar

#### A. Rodando Localmente com Docker Compose
Se a rede `easypanel` não existir na sua máquina local de desenvolvimento, crie-a uma única vez:
```bash
docker network create easypanel
```
Em seguida, inicialize:
```bash
docker compose up -d --build
```
Verifique o status e os logs:
```bash
docker compose ps
docker compose logs -f
```
Teste o healthcheck:
```bash
curl http://localhost:8000/health
```

#### B. Subindo no Easypanel (Produção)
1. Crie um **App Service** no Easypanel e aponte para o repositório Git.
2. Defina o **Build Type**: `Dockerfile`.
3. Defina a porta da aplicação: `8000`.
4. Configure as variáveis de ambiente necessárias.
5. Se for usar via **Docker Compose** no Easypanel:
   - Cole o conteúdo do `docker-compose.yml`.
   - Como o Easypanel já possui a rede `easypanel` criada, o bind e a descoberta de serviço serão automáticos.

---

## 🛠️ 5. Resumo das Decisões e Soluções de Erros Conhecidos

| Desafio Encontrado | Causa Raiz | Solução Aplicada |
| :--- | :--- | :--- |
| **Imagem muito pesada e lenta** | Uso de imagens full Python (`python:3.12`) com compiladores desnecessários | Migração para `python:3.12-slim` + `--no-cache-dir` no pip |
| **Reinstalação lenta de libs a cada commit** | Copiar o código fonte antes de rodar `pip install` | Inversão: `COPY requirements.txt` -> `RUN pip install` -> `COPY app...` |
| **Logs não aparecendo no Easypanel** | Buffer interno de saída do Python ativo | `ENV PYTHONUNBUFFERED=1` |
| **Falha de Healthcheck no contêiner slim** | Imagens `slim` não incluem utilitários `curl` ou `wget` | Healthcheck via comando inline Python: `python -c "import urllib.request; ..."` |
| **Container não responde na porta mapeada** | Aplicação Uvicorn escutando em `127.0.0.1` | Inicializar com `--host 0.0.0.0` |
| **Traefik do Easypanel não roteia o domínio** | Contêiner isolado em rede bridge default sem acesso à rede do Easypanel | Adicionar `networks: [default, easypanel]` com `external: true` |
| **n8n não encontra o arquivo PDF** | n8n enviou campo binário como `data` ou binário direto em vez de `file` | Tratamento flexível no FastAPI: aceitar `file`, `data`, `attachment` e raw stream |
