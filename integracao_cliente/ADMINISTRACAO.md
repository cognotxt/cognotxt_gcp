# CognoTXT B2B — Administração e implantação (MVP)

## Arquitetura

```text
Frontend Firebase (INALTERADO) ---> API /uploads/session, /jobs, /download
                                            |
Cliente B2B -- X-API-Key ---> API /v1/uploads, /v1/jobs
                                |           |
                           Firestore     GCS sessão de upload
                            empresas      uploads/b2b_{empresa}_{key}/{job}/file.pdf
                            API Keys             |
                            rate_limits        Eventarc --> Dispatcher --> Worker --> TXT
                                |                                   |
                            uso/cotas  <--- contadores do worker ---+
```

A API guarda apenas `SHA-256(token aleatório)`. `api_key` em texto claro é retornada somente ao criar a chave. **Não** use esta solução para senhas humanas. Os identificadores `company_id` e `api_key_id` são armazenados nos jobs e também no namespace de objetos.

## Deploy seguro (sem recriar Eventarc)

1. Faça commit/backup do projeto que funciona. Este pacote modifica somente `api/main.py`, adiciona `api/b2b.py` e modifica `worker/main.py`. Os comentários originais foram preservados.
2. Na conta Firebase do administrador, confirme que `email_verified=true`.
3. **Primeiro configure a allowlist** do administrador; se não houver `B2B_ADMIN_EMAILS`, as rotas administrativas negam todo acesso. O exemplo usa um único e-mail, não coloque segredos nas variáveis.

```bash
PROJECT_ID=grafemapdf
REGION=us-central1
ADMIN_EMAIL='admin@empresa.com.br' # ALTERAR: e-mail Firebase verificado do administrador

gcloud run services update cognotxt-api \
  --project="$PROJECT_ID" --region="$REGION" \
  --update-env-vars="B2B_ADMIN_EMAILS=$ADMIN_EMAIL"
```

4. Build e deploy, preservando as variáveis atuais, service accounts e Eventarc:

```bash
gcloud builds submit ./api --project="$PROJECT_ID" \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/api:latest"
gcloud builds submit ./worker --project="$PROJECT_ID" \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/worker:latest"

gcloud run deploy cognotxt-api --project="$PROJECT_ID" --region="$REGION" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/api:latest" \
  --service-account="cognotxt-api@$PROJECT_ID.iam.gserviceaccount.com" \
  --allow-unauthenticated

gcloud run jobs update cognotxt-worker --project="$PROJECT_ID" --region="$REGION" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/worker:latest"
```

5. Confira `/health`, `/openapi.json`, `/docs` e o frontend Firebase ANTES de provisionar clientes reais.
6. **Não execute `infra/deploy.sh`** para esta evolução: versões antigas recriam trigger Eventarc e sobrescrevem variáveis.

## Provisionamento de empresas e API Keys

O administrador se autentica com um **Firebase ID Token válido** de uma conta cujo e-mail está listado em `B2B_ADMIN_EMAILS` e verificado pelo Firebase. `ADMIN_TOKEN` **não** é a API Key.

```bash
export BASE_URL='https://cognotxt-api-940153605624.us-central1.run.app'
export ADMIN_TOKEN='TOKEN_FIREBASE_DO_ADMINISTRADOR'

curl -X POST "$BASE_URL/admin/companies" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Empresa Exemplo", "description":"Cliente corporativo", "contact_email":"contato@exemplo.com"}'
```

Guarde `company_id` retornado; depois crie credenciais separadas para cada departamento:

```bash
curl -X POST "$BASE_URL/admin/companies/$COMPANY_ID/keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "alias":"financeiro-prod", "department":"Financeiro", "description":"Integração ERP",
    "environment":"production", "valid_from":"2026-11-01T00:00:00-03:00",
    "valid_until":"2027-10-31T23:59:59-03:00",
    "rpm_limit":60,"concurrency_limit":3,"monthly_page_limit":100000,
    "scopes":["jobs:create","jobs:read","jobs:download"]
  }'
```

Resposta contém `api_key` **uma única vez**. Não copie para tickets, prints, logs ou Git. Para rotação sem indisponibilidade: emita outra chave, atualize o consumidor, verifique o funcionamento e só então execute `POST /admin/keys/{key_id}/revoke`.

Outras rotas: `GET /admin/companies`, `GET /admin/companies/{id}/keys`, `POST /admin/keys/{id}/suspend`, `POST /admin/keys/{id}/activate`, `PATCH /admin/companies/{id}/status?active=false`, `GET /admin/companies/{id}/usage`.

## Quotas e observações operacionais

- Por API Key: RPM com janelas de 1 minuto via documentos Firestore, e contador atômico de execuções reservadas no momento da criação do job. **O contador só é liberado ao concluir o worker ou se a criação da sessão falhar**.
- Limites mensais: esta primeira versão aplica o teto sobre as **páginas concluídas contabilizadas**. PDFs já em andamento podem ultrapassar o teto antes do registro; contratos com orçamento rígido exigem reserva estimada de páginas no upload.
- Arquivos cujo upload foi abandonado antes de finalizar ficam com slot reservado; é necessária uma rotina periódica de expiração/reconciliação antes de operar volume elevado.
- Contadores de `processing_seconds_total`, `pages_total`, `errors_total`, `jobs_total` são acumulados por API Key. Histórico de detalhamento está em `jobs` com `company_id` e `api_key_id`.
- A listagem de jobs recupera até 300 itens e retorna os mais recentes após ordenação; para milhares de jobs será necessário paginação por cursor.
- Endpoint administrativo requer e-mail Firebase verificado e allowlist explícita. Proteja o acesso administrativo também por políticas corporativas de identidade, MFA e auditoria.
- Rotas públicas do serviço ainda aceitam HTTP sem IAM do Cloud Run para preservar o frontend. A API Key é a camada de autenticação da API B2B; recomenda-se Cloud Armor/API Gateway na expansão comercial.
- Webhooks **não implementados**: serão uma evolução posterior com assinatura HMAC, proteção SSRF, retries e DLQ.
- `infra/config.env`, `.git/`, `.venv/`, `.idea/` e chaves privadas não entram no ZIP de entrega.

## Testes mínimos em homologação

1. Criar empresa, criar duas API Keys distintas, testar chaves em diferentes datas/estados.
2. Executar cliente de exemplo com um PDF simples e obter TXT.
3. Consultar job de chave A com chave B: resposta `404`.
4. Revogar chave A e demonstrar que B continua operando.
5. Testar quota RPM e `concurrency_limit`, inclusive chamadas concorrentes.
6. Confirmar que upload, preview e ZIP no frontend Firebase permanecem funcionando.
7. Validar contadores e verificar que o Worker contabiliza exatamente uma vez.
8. Homologar o ciclo de recuperação de uploads interrompidos antes de disponibilizar em escala.
