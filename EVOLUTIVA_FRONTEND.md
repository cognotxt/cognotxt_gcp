# CognoTXT — Evolutiva frontend v2 (revisada)

**Verificação contra o projeto original:** `frontend/index.html`, `frontend/styles.css` e `frontend/app.js` têm alterações reais;
veja `RELATORIO_COMPARACAO.md` e `diffs/` no pacote.

**Localização dos arquivos no ZIP completo:** `cognotxt_gcp/frontend/`. Existe também um ZIP menor, 
`cognotxt_frontend_apenas.zip`, com `frontend/` na raiz para facilitar a publicação no GitHub Pages.

**Atenção:** o HTML agora usa `styles.css?v=2` e `app.js?v=2` para minimizar efeitos do cache do navegador. 
Substitua os três arquivos juntos, mantendo seu `config.js` ativo.

**Backend:** as funcionalidades de prévia e ZIP dependem da implantação dos arquivos alterados `api/main.py` e `worker/main.py`. 
Se publicar apenas o frontend, contadores e filtros funcionam parcialmente com os dados existentes, mas as novas ações não.

---

# CognoTXT — Evolutiva de acompanhamento (20/10/2026)

## O que mudou

Esta entrega foi elaborada **sobre o projeto original**, preservando os comentários existentes e 
as rotas anteriores de autenticação, upload resumable, listagem de jobs e download individual.

- **Contador de páginas**: usa os campos já existentes no Firestore `processed_pages` e `total_pages`.
- **Tempo decorrido, conclusão e previsão de término**: calculado no navegador a partir de `started_at`, `finished_at`, `processed_pages` e `total_pages`. A previsão é aproximada, baseada na velocidade média efetivamente observada. No início, aparece "calculando estimativa".
- **Tamanho e quantidade total de páginas**: a API registra `file_size` ao criar o job e o worker registra a contagem de páginas assim que termina de baixar/abrir o PDF.
- **Busca, filtro por status e resumos**: totalmente no frontend; sem novas dependências.
- **Detalhes de erros**: botão aparece para jobs com erro registrado.
- **Prévia segura**: `GET /jobs/{job_id}/preview` autentica o usuário, verifica o proprietário e lê no máximo os primeiros 16 KiB do TXT no GCS.
- **Download em ZIP**: `POST /jobs/download-zip` recebe `{"job_ids":["..."]}`, valida acesso a todos, aceita até 20 TXTs por solicitação e limita a soma a 40 MiB. A resposta é binária `application/zip`. ZIP gerado em memória; adequado a lotes pequenos e médios.
- **Ocultar concluídos**: apenas na tabela da sessão atual; **não exclui** arquivos, Firestore ou Storage. Recarregar a página volta a mostrar tudo.
- **Atualizações quase em tempo real**: preservado o polling autenticado a cada **3 segundos**, que já funcionava na aplicação. Não foram adicionados WebSocket/SSE, nem infraestrutura adicional.

## Arquivos modificados

- `frontend/index.html` — componentes da tabela, resumo, filtros e modal.
- `frontend/styles.css` — estilos, cores de estado e responsividade.
- `frontend/app.js` — renderização dinâmica, estimativa, filtros, seleção, prévia e ZIP.
- `api/main.py` — metadado `file_size`, rota de prévia e rota ZIP.
- `worker/main.py` — registra total de páginas após baixar o PDF, antes do OCR.

`worker/processor.py`, `dispatcher/main.py`, as funções originais de upload resumable e o fluxo de geração de TXT **não foram alterados**.

## Implantação segura

1. Faça backup ou commit da versão operacional atual.
2. Atualize no repositório os cinco arquivos modificados. Preserve `frontend/config.js` e suas configurações válidas; não há necessidade de trocar credenciais ou URLs.
3. Reconstrua **somente** as imagens `api` e `worker`, a partir da raiz do repositório:

```bash
PROJECT_ID=grafemapdf
REGION=us-central1

gcloud builds submit ./api \
  --project="$PROJECT_ID" \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/api:latest"

gcloud builds submit ./worker \
  --project="$PROJECT_ID" \
  --tag "$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/worker:latest"
```

4. Implante API preservando as variáveis de ambiente **já configuradas** (não use `--set-env-vars` nem recrie o Eventarc):

```bash
gcloud run deploy cognotxt-api \
  --project="$PROJECT_ID" --region="$REGION" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/api:latest" \
  --service-account="cognotxt-api@$PROJECT_ID.iam.gserviceaccount.com" \
  --allow-unauthenticated
```

5. Atualize a imagem do job, preservando os parâmetros, permissões e variáveis atuais:

```bash
gcloud run jobs update cognotxt-worker \
  --project="$PROJECT_ID" --region="$REGION" \
  --image="$REGION-docker.pkg.dev/$PROJECT_ID/cognotxt/worker:latest"
```

6. Publique os três arquivos modificados da pasta `frontend/` no GitHub Pages (`index.html`, `app.js`, `styles.css`). **Não altere `config.js`**,
caso a URL atual da API esteja correta.
7. Force a atualização do navegador (Ctrl+F5) e teste com PDF pequeno, depois com um arquivo grande.

**Não execute `infra/deploy.sh` integralmente apenas para esta evolutiva**: ele também altera o dispatcher, o job, serviços IAM e o Eventarc. Esta mudança não precisa disso.

## Testes de aceitação sugeridos

1. Login, upload resumable e processamento completo permanecem funcionando.
2. Durante OCR exibe `X de Y págs` e percentagem; depois de algumas páginas mostra estimativa aproximada.
3. Em `COMPLETED`, mostra tempo total e botões `Baixar TXT` e `Prévia`.
4. Busca por nome e filtro por status funcionam sem nova chamada ao backend.
5. Prévia não mostra mais de 16 KiB, nunca exibe TXT de outro usuário.
6. Download ZIP com 2 TXTs concluídos funciona; erro informativo para seleção acima de 20 ou total acima de 40 MiB.
7. `Ocultar concluídos` não apaga documentos; recarregar página os exibe novamente.
8. Erros exibem detalhe, sem expor tokens nem URLs de sessões de upload.

## Observações e próximos passos

- A estimativa é uma média linear, não uma garantia: páginas com OCR difícil e tabelas podem demorar mais.
- Como o worker atual grava progresso a cada página, o frontend apenas lê esses registros existentes. Em volumes maiores, agrupar atualizações do Firestore (por exemplo a cada 2–5 páginas ou a cada 3 segundos) pode reduzir escrita/custo.
- PDFs antigos sem `file_size` não exibirão tamanho; jobs antigos sem `started_at`/`finished_at` não exibirão duração.
- Para milhares de TXTs em um único ZIP, recomenda-se uma tarefa assíncrona dedicada, não gerar arquivos muito grandes na API com 512 MiB de memória.
- O projeto continua preparado para uma futura migração opcional do polling para SSE, se o volume de usuários simultâneos justificar.
