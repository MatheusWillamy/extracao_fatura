import io
import base64
import logging
from typing import Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, Request, Query, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from extractor import extract_fatura, format_api_response

logger = logging.getLogger("api_fatura")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="API de Extração de Faturas Enel",
    description="API para extração de dados estruturados de faturas de energia (Enel/AJDC), compatível com n8n e FlutterFlow.",
    version="1.1.0"
)

# Enable CORS for FlutterFlow web and other frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Base64InvoiceRequest(BaseModel):
    file_base64: Optional[str] = None
    data: Optional[str] = None
    file: Optional[str] = None
    mode: Optional[str] = "auto"
    wrap_output: Optional[bool] = True


async def _get_pdf_bytes_from_request(
    request: Request,
    file: Optional[UploadFile] = None
) -> bytes:
    """Extracts PDF bytes from multipart upload, raw body, or JSON base64."""
    # 1. Multipart form file
    if file is not None:
        return await file.read()

    # 2. Check Content-Type
    content_type = request.headers.get("content-type", "").lower()

    if "application/pdf" in content_type or "application/octet-stream" in content_type:
        raw_body = await request.body()
        if raw_body:
            return raw_body

    if "application/json" in content_type:
        try:
            body_json = await request.json()
            b64_str = (
                body_json.get("file_base64") or
                body_json.get("data") or
                body_json.get("file") or
                body_json.get("content")
            )
            if b64_str:
                # Remove data:application/pdf;base64, prefix if present
                if "," in b64_str:
                    b64_str = b64_str.split(",")[1]
                return base64.b64decode(b64_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Erro ao decodificar JSON/Base64: {str(e)}")

    # 3. Fallback: try raw body
    raw_body = await request.body()
    if raw_body and raw_body.startswith(b"%PDF"):
        return raw_body

    raise HTTPException(
        status_code=400,
        detail="Nenhum arquivo PDF fornecido. Envie via multipart/form-data (campo 'file'), corpo binário application/pdf, ou JSON com base64 ('file_base64'/'data')."
    )


@app.get("/")
def root():
    return {
        "service": "API Extração de Faturas Enel",
        "version": "1.1.0",
        "status": "online",
        "docs": "/docs",
        "endpoints": {
            "extract": "POST /extract",
            "n8n_webhook_compat": "POST /homo_extracao_enel",
            "health": "GET /health"
        }
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "api-extracao-fatura", "version": "1.1.0"}


@app.post("/extract")
@app.post("/homo_extracao_enel")
@app.post("/webhook")
async def extract_invoice_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    mode: str = Query("auto", description="Modo de extração: 'auto', 'structured' ou 'ai'"),
    wrap_output: bool = Query(True, description="Inclui chave 'output' aninhada para compatibilidade total com n8n"),
    x_api_key: Optional[str] = Header(None, description="Chave de API de IA opcional se modo 'ai' for usado")
):
    """
    Extrai todos os dados da fatura de energia em formato estruturado estrito.
    Compatível diretamente com o n8n e FlutterFlow.
    """
    try:
        pdf_bytes = await _get_pdf_bytes_from_request(request, file)
        
        # Check if json body requested a specific mode or wrap_output
        if request.headers.get("content-type", "").startswith("application/json"):
            try:
                body_json = await request.json()
                if "mode" in body_json:
                    mode = body_json["mode"]
                if "wrap_output" in body_json:
                    wrap_output = body_json["wrap_output"]
            except Exception:
                pass

        extracted = await extract_fatura(
            pdf_source=pdf_bytes,
            mode=mode,
            api_key=x_api_key
        )
        
        response_data = format_api_response(extracted, wrap_output=wrap_output)
        return JSONResponse(content=response_data, status_code=200)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro durante a extração da fatura")
        return JSONResponse(
            status_code=500,
            content={"error": f"Erro interno ao processar o arquivo: {str(e)}"}
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
