# Integração CognoTXT API v1 (cliente)

A API oferece OCR assíncrono de PDFs e TXT resultante. Não é necessário utilizar o frontend ou Firebase Authentication: a integração usa `X-API-Key`.

**Nota de implantação:** esses endpoints são parte da evolutiva e só existirão após o deploy da nova API. O exemplo de endereço abaixo usa a URL atual do Cloud Run; se houver domínio corporativo, substitua `BASE_URL`.

## 1. Credenciais

Solicite ao administrador CognoTXT uma API Key para o seu departamento. Cada chave tem `alias`, descrição, datas de validade, escopos, cota RPM, concorrência e limite mensal de páginas. A chave é exibida uma única vez no cadastro. Guarde-a no cofre de segredos do sistema (nunca em HTML, JS do navegador, Git ou logs).

```bash
export BASE_URL='https://cognotxt-api-940153605624.us-central1.run.app'
export COGNOTXT_API_KEY='COLE_A_CHAVE_FORNECIDA_EM_AMBIENTE_SEGURO'
```

## 2. Criar processamento

```bash
PDF=./documento.pdf
BYTES=$(wc -c < "$PDF" | tr -d ' ')
curl -sS -f -X POST "$BASE_URL/v1/uploads" \
  -H "X-API-Key: $COGNOTXT_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"filename\":\"documento.pdf\",\"size\":$BYTES,\"content_type\":\"application/pdf\"}"
```

Resposta típica:

```json
{"job_id":"<uuid>","status":"UPLOADING","upload_url":"https://storage.googleapis.com/upload/...","upload_method":"PUT","upload_content_type":"application/pdf"}
```

`upload_url` é uma credencial temporária: proteja-a e nunca publique seu conteúdo. O endpoint cria a sessão de upload resumível do Google Cloud Storage.

## 3. Transferir o PDF

Para PDFs pequenos ou médios, o exemplo usa um único PUT. Para transferências muito grandes e retomáveis, implemente o protocolo de upload resumível do GCS com `Content-Range`.

```bash
curl -sS -f -X PUT "$UPLOAD_URL" \
  -H 'Content-Type: application/pdf' \
  -H "Content-Length: $BYTES" \
  --data-binary '@documento.pdf'
```

**Não** envie `X-API-Key` para `storage.googleapis.com`. Um upload completo emite evento `OBJECT_FINALIZE` e aciona o worker existente.

## 4. Acompanhar processamento

```bash
curl -sS "$BASE_URL/v1/jobs/$JOB_ID" -H "X-API-Key: $COGNOTXT_API_KEY"
```

Resposta ilustrativa:

```json
{"job_id":"<uuid>","status":"PROCESSING","filename":"documento.pdf", "total_pages":700,"processed_pages":420,"progress_percent":60,"elapsed_seconds":320,"estimated_remaining_seconds":213}
```

Estados típicos: `UPLOADING`, `QUEUED`, `PROCESSING`, `COMPLETED`, `ERROR`. Consulte a cada 10–15 segundos, respeitando a quota por minuto. Os tempos são aproximados e podem variar com OCR/tabelas.

## 5. Download

```bash
curl -sS "$BASE_URL/v1/jobs/$JOB_ID/download" -H "X-API-Key: $COGNOTXT_API_KEY"
```

Resposta:

```json
{"url":"https://storage.googleapis.com/...","expires_in_minutes":15}
```

Baixe o TXT usando a URL recém-recebida. Ela é assinada e expira; ao expirar, solicite outra. Não exponha URLs assinadas em logs ou compartilhamentos.

## 6. Erros e segurança

- `401`: chave ausente/inválida; confirmar variável de ambiente e credencial.
- `403`: chave suspensa, expirada, fora da validade ou sem escopo.
- `404`: job inexistente ou pertencente a outra API Key.
- `409`: TXT ainda não concluído.
- `413`: PDF acima do limite configurado.
- `429`: excesso de RPM, limite de processamentos simultâneos ou limite mensal de páginas; aguarde antes de repetir.
- `500`/`503`: falha transitória; use retentativas controladas, **sem duplicar o envio de jobs automaticamente**.

Para recuperação de um timeout depois de `POST /v1/uploads`, guarde o `job_id` assim que recebido. A primeira versão não oferece chave de idempotência de criação. Não repita automaticamente chamadas de criação sem saber se o servidor aceitou a anterior.

## 7. Python completo

Use `cliente.py` nesta pasta:

```bash
pip install requests
export COGNOTXT_API_URL="$BASE_URL"
python cliente.py documento.pdf
```

## 8. OpenAPI

Acesse `https://SEU_SERVICO/docs` (Swagger UI) ou `/openapi.json` para conferir os modelos. Rotas administrativas `/admin/...` requerem um **Firebase ID Token de administrador**, não uma API Key.

## 9. Webhooks (roadmap)

A primeira versão usa polling. Webhooks com entrega assinada HMAC, validação de endpoint e retentativas são evolução futura e **não estão implementados neste pacote**.
