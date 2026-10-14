# CognoTXT Cloud — implantação em produção na Google Cloud

Este pacote coloca o processamento de PDFs na nuvem com:

- login por e-mail/senha com Firebase Authentication;
- frontend estático em `https://cognotxt.com.br` (GitHub Pages);
- upload resumável direto do navegador para Google Cloud Storage;
- bucket privado e CORS restrito ao domínio;
- gatilho automático após finalizar o upload;
- processamento assíncrono em Cloud Run Job;
- OCR inteligente com Google Document AI;
- Enterprise Document OCR como OCR principal;
- Form Parser somente para tabelas rasterizadas;
- PyMuPDF + OpenCV para texto nativo, imagens e detecção local de tabelas;
- status/progresso no Firestore;
- geração de `.txt` e download temporário por URL assinada.

## 1. Estrutura

```text
cognotxt_cloud/
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── config.example.js
├── api/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── dispatcher/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── worker/
│   ├── main.py
│   ├── processor.py
│   ├── requirements.txt
│   └── Dockerfile
└── infra/
    ├── config.env.example
    ├── cors.json
    ├── deploy.sh
    ├── check.sh
    └── firestore.rules
```

---

# PARTE A — PREPARAÇÃO

## 2. O que você precisa antes de começar

Tenha em mãos:

1. Um projeto Google Cloud com faturamento ativo.
2. O `Project ID`.
3. O Enterprise Document OCR já criado.
4. O Processor ID do Enterprise Document OCR.
5. O Form Parser já criado, se quiser reconhecimento estruturado de tabelas rasterizadas.
6. O Processor ID do Form Parser.
7. Acesso administrativo ao projeto.
8. Seu domínio `cognotxt.com.br` apontando para o GitHub Pages.

Recomendação inicial deste pacote:

```text
Cloud Run / Storage / Eventarc: us-central1
Document AI: us
```

O Document AI usa a localização do processor (`us` neste exemplo). Se seus documentos tiverem requisito formal de residência de dados, valide a região antes de colocar documentos reais de clientes em produção.

---

# PARTE B — FIREBASE AUTHENTICATION

## 3. Adicionar Firebase ao projeto Google Cloud existente

1. Abra:

   https://console.firebase.google.com/

2. Clique em **Adicionar projeto**.
3. Escolha **Adicionar Firebase a um projeto do Google Cloud existente**.
4. Selecione o mesmo projeto usado pelo Document AI.
5. Conclua a associação.

## 4. Habilitar login por e-mail e senha

No Firebase Console:

1. Vá em **Build > Authentication**.
2. Clique em **Começar**.
3. Entre em **Sign-in method / Método de login**.
4. Selecione **Email/Password**.
5. Ative **Email/Password**.
6. Salve.

## 5. Criar o primeiro usuário

1. Ainda em **Authentication**.
2. Abra a aba **Users / Usuários**.
3. Clique em **Add user**.
4. Informe o e-mail do cliente/administrador.
5. Crie uma senha inicial.

Para a primeira versão, recomendo que você mesmo cadastre os usuários. Depois podemos criar uma tela administrativa.

## 6. Autorizar o domínio

No Firebase Authentication:

1. Abra **Settings / Configurações**.
2. Procure **Authorized domains**.
3. Adicione:

```text
cognotxt.com.br
www.cognotxt.com.br
```

## 7. Registrar o aplicativo Web

No Firebase Console:

1. Abra **Project settings / Configurações do projeto**.
2. Na seção **Your apps**, clique no ícone Web `</>`.
3. Nome: `CognoTXT Web`.
4. Registre o app.
5. O Firebase mostrará algo parecido com:

```javascript
const firebaseConfig = {
  apiKey: "...",
  authDomain: "...",
  projectId: "...",
  storageBucket: "...",
  messagingSenderId: "...",
  appId: "..."
};
```



```text
npm install firebase
```


```javascript
// Import the functions you need from the SDKs you need
import { initializeApp } from "firebase/app";
import { getAnalytics } from "firebase/analytics";
// TODO: Add SDKs for Firebase products that you want to use
// https://firebase.google.com/docs/web/setup#available-libraries

// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyBf_PnqYf9zm1kX00D9M4Ot0YZtWOFENyA",
  authDomain: "grafemapdf.firebaseapp.com",
  projectId: "grafemapdf",
  storageBucket: "grafemapdf.firebasestorage.app",
  messagingSenderId: "940153605624",
  appId: "1:940153605624:web:77895fdf6ba81721f61a0d",
  measurementId: "G-62WE0W3YKQ"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const analytics = getAnalytics(app);
```

Guarde esses valores. Eles serão colocados no `frontend/config.js`.

**Importante:** a configuração web do Firebase não é uma chave privada. A segurança está nas regras, no Firebase Authentication e na validação do token no backend.

---

# PARTE C — FIRESTORE

## 8. Criar Firestore

No Google Cloud Console:

1. Procure **Firestore**.
2. Clique em **Criar banco de dados**.
3. Escolha **Standard edition**.
4. Escolha **Native mode / Modo nativo**.
5. Use o banco `(default)`.
6. Região recomendada para este exemplo: `us-central1`.
7. Nas regras iniciais, escolha configuração restritiva.
8. Crie o banco.

O navegador não acessa o Firestore diretamente nesta versão. Todo acesso passa pelos serviços Cloud Run usando IAM.

---

# PARTE D — CLOUD SHELL

## 9. Usar o Cloud Shell

Para alguém que não é especialista em Google Cloud, esta é a forma mais simples.

1. Entre em:

   https://console.cloud.google.com/

2. Selecione seu projeto.
3. No canto superior direito clique no ícone `>_` **Activate Cloud Shell**.
4. Aguarde abrir o terminal na parte inferior da tela.

Você não precisa instalar o `gcloud` no seu computador se usar o Cloud Shell.

## 10. Enviar este projeto para o Cloud Shell

Você pode:

- colocar os arquivos em um repositório Git e executar `git clone`; ou
- usar o menu do Cloud Shell para fazer upload do ZIP deste pacote.

Depois entre na pasta:

```bash
cd cognotxt_cloud
```

---

# PARTE E — CONFIGURAÇÃO DO DEPLOY

## 11. Criar o arquivo de configuração

No Cloud Shell:

```bash
cp infra/config.env.example infra/config.env
nano infra/config.env
```

Preencha:

```bash
PROJECT_ID=meu-projeto-google
REGION=us-central1
BUCKET_NAME=meu-projeto-google-cognotxt
FRONTEND_ORIGIN=https://cognotxt.com.br
FRONTEND_ORIGIN_WWW=https://www.cognotxt.com.br
DOCUMENT_AI_LOCATION=us
GOOGLE_OCR_PROCESSOR_ID=ID_DO_ENTERPRISE_OCR
GOOGLE_FORM_PROCESSOR_ID=ID_DO_FORM_PARSER
MAX_FILE_MB=2048
```

Salve no `nano`:

```text
Ctrl+O
Enter
Ctrl+X
```

### BUCKET_NAME

O nome do bucket precisa ser globalmente único. Se:

```text
meu-projeto-google-cognotxt
```

já existir, use algo mais específico, por exemplo:

```text
cognotxt-meu-projeto-2026
```

---

# PARTE F — EXECUTAR O DEPLOY

## 12. Conferir o projeto ativo

```bash
gcloud config get-value project
```

Se necessário:

```bash
gcloud config set project SEU_PROJECT_ID
```

## 13. Executar o script

```bash
chmod +x infra/deploy.sh
./infra/deploy.sh
```

O script fará:

1. ativação das APIs;
2. criação das Service Accounts;
3. permissões IAM;
4. criação/configuração do bucket;
5. CORS;
6. Artifact Registry;
7. build dos containers;
8. Cloud Run Job OCR;
9. Cloud Run Dispatcher;
10. Cloud Run API;
11. Eventarc para `OBJECT_FINALIZE`.

A primeira execução pode levar alguns minutos porque três imagens Docker serão construídas.

No final aparecerá:

```text
DEPLOY CONCLUÍDO
API URL: https://cognotxt-api-xxxxxxxxxx-uc.a.run.app
Bucket: gs://...
```

Copie a **API URL**.

---

# PARTE G — CONFIGURAR O FRONTEND

## 14. Criar `frontend/config.js`

No seu computador, copie:

```text
frontend/config.example.js
```

para:

```text
frontend/config.js
```

Preencha com a URL do Cloud Run e os dados do Firebase:

```javascript
export const CONFIG = {
  apiBaseUrl: "https://cognotxt-api-xxxxxxxxxx-uc.a.run.app",
  firebase: {
    apiKey: "...",
    authDomain: "seu-projeto.firebaseapp.com",
    projectId: "seu-projeto",
    storageBucket: "seu-projeto.firebasestorage.app",
    messagingSenderId: "...",
    appId: "..."
  }
};
```

## 15. Colocar no GitHub Pages

Você já utiliza `cognotxt.com.br` no GitHub Pages.

Coloque no repositório publicado:

```text
index.html
styles.css
app.js
config.js
```

Se o seu GitHub Pages já tem uma landing page que você quer manter, coloque estes arquivos em uma subpasta, por exemplo:

```text
/app/index.html
/app/styles.css
/app/app.js
/app/config.js
```

Nesse caso o sistema ficará em:

```text
https://cognotxt.com.br/app/
```

Se fizer isso, atualize `FRONTEND_ORIGIN`? **Não.** A origem continua sendo somente:

```text
https://cognotxt.com.br
```

O caminho `/app/` não faz parte da origem CORS.

---

# PARTE H — COMO O SISTEMA FUNCIONA

## 16. Login

O usuário entra com e-mail/senha.

O Firebase fornece um ID Token. O JavaScript envia:

```text
Authorization: Bearer <Firebase ID Token>
```

para a API.

A API valida esse token antes de criar upload, listar jobs ou permitir download.

## 17. Upload resumável

O navegador primeiro pede à API:

```text
POST /uploads/session
```

A API cria uma sessão temporária de upload no Cloud Storage.

Depois o PDF vai diretamente:

```text
Navegador -> Google Cloud Storage
```

O arquivo não passa pela memória do Cloud Run API.

O frontend envia em blocos de 8 MiB e acompanha o progresso.

Se houver interrupção, ele consulta a posição já gravada e tenta continuar.

## 18. Caminho do arquivo

Entrada:

```text
uploads/{uid}/{job_id}/arquivo.pdf
```

Saída:

```text
outputs/{uid}/{job_id}/arquivo_DATA_HORA.txt
```

Cada usuário fica isolado logicamente pelo UID do Firebase.

## 19. Gatilho automático

Quando o upload termina, o Cloud Storage emite:

```text
google.cloud.storage.object.v1.finalized
```

O Eventarc envia o evento ao `cognotxt-dispatcher`.

O dispatcher ignora objetos de `outputs/`; ele só processa caminhos que começam com:

```text
uploads/
```

Em seguida executa o Cloud Run Job `cognotxt-worker`.

## 20. OCR inteligente

O worker executa página por página.

### Página digital

```text
PyMuPDF -> texto nativo
```

Evita custo de OCR desnecessário.

### Página digital com tabela

```text
PyMuPDF.find_tables() -> tabela ASCII completa
```

Sem truncar células.

### Página somente imagem

```text
renderização -> Enterprise Document OCR
```

### Imagem com provável tabela

Primeiro uma heurística local com OpenCV procura linhas horizontais e verticais.

Somente quando houver forte indicação de tabela:

```text
Form Parser
```

Isso reduz o uso do Form Parser e consequentemente o custo.

### Página mista

A saída respeita a ordem espacial:

```text
texto A
imagem B -> OCR
texto C
tabela D
```

## 21. Formato do TXT

Exemplo:

```text
Arquivo: processo.pdf
Total de páginas: 688

========== PÁGINA 1 DE 688 ==========
Texto...

========== PÁGINA 2 DE 688 ==========
PÁGINA EM BRANCO

========== PÁGINA 3 DE 688 ==========
Texto...
```

Tabelas:

```text
+------------------------------------------------------------------+-----+
| PONTUAÇÃO MÁXIMA DO PLANO DE TRABALHO                            | 170 |
+------------------------------------------------------------------+-----+
| Bloco 1- Execução das atividades do Plano de Trabalho            | 110 |
+------------------------------------------------------------------+-----+
| Bloco1 Quadro1-aderência do Plano de Trabalho à Proposta Técnica | 70  |
+------------------------------------------------------------------+-----+
```

---

# PARTE I — PROGRESSO

## 22. Status utilizados

```text
UPLOADING
QUEUED
PROCESSING
COMPLETED
ERROR
```

O worker atualiza no Firestore:

```text
processed_pages
total_pages
processing_progress
status
```

O frontend consulta a API a cada 3 segundos.

Isto evita abrir o Firestore diretamente para o navegador e mantém a primeira versão mais simples e segura.

---

# PARTE J — DOWNLOAD

## 23. Download seguro

Quando o job estiver `COMPLETED`, o frontend mostra:

```text
Baixar TXT
```

Ao clicar, a API:

1. valida o usuário Firebase;
2. verifica se o `uid` é dono do job;
3. gera uma Signed URL V4 temporária;
4. retorna o link ao navegador.

A URL expira, por padrão, em 15 minutos.

O bucket não precisa ficar público.

---

# PARTE K — TESTE

## 24. Testar os componentes

No Cloud Shell:

```bash
./infra/check.sh
```

Você deverá ver:

- `cognotxt-api`;
- `cognotxt-dispatcher`;
- job `cognotxt-worker`;
- trigger `cognotxt-storage-finalized`;
- configuração CORS do bucket.

## 25. Teste funcional

1. Abra `https://cognotxt.com.br/` ou `/app/`.
2. Entre com o usuário criado no Firebase.
3. Selecione um PDF pequeno para o primeiro teste.
4. Observe a barra de upload chegar a 100%.
5. O status deverá mudar para `Na fila`.
6. Depois `Processando`.
7. A barra de processamento deve avançar página por página.
8. Ao terminar: `Pronto`.
9. Clique em `Baixar TXT`.

Depois faça teste com PDF maior.

---

# PARTE L — LOGS E DIAGNÓSTICO

## 26. Ver logs da API

```bash
gcloud run services logs read cognotxt-api --region=us-central1 --limit=100
```

## 27. Ver logs do dispatcher

```bash
gcloud run services logs read cognotxt-dispatcher --region=us-central1 --limit=100
```

## 28. Ver execuções do worker

```bash
gcloud run jobs executions list --job=cognotxt-worker --region=us-central1
```

Para acompanhar uma execução, também é possível usar o Console:

```text
Cloud Run -> Jobs -> cognotxt-worker -> Executions
```

## 29. Ver objetos no bucket

```bash
gcloud storage ls -r gs://SEU_BUCKET/**
```

---

# PARTE M — SEGURANÇA

## 30. Não use chave JSON de Service Account no Cloud Run

O código local anterior usava:

```text
GOOGLE_APPLICATION_CREDENTIALS=...
```

Na produção isso não é necessário.

Cada serviço Cloud Run recebe uma Service Account própria:

```text
cognotxt-api
cognotxt-dispatcher
cognotxt-worker
cognotxt-eventarc
```

As credenciais são fornecidas automaticamente pela infraestrutura da Google.

Não coloque JSON de Service Account dentro da imagem Docker ou GitHub.

## 31. Bucket privado

Não habilite:

```text
allUsers
```

nem acesso público ao bucket.

O upload usa sessão temporária e o download usa Signed URL temporária.

---

# PARTE N — PRODUÇÃO E CUSTO

## 32. Comece pequeno

Antes de liberar centenas de arquivos de uma vez, teste aproximadamente:

```text
5 PDFs
10 PDFs
20 PDFs
```

Meça:

- tempo médio por página;
- custo Document AI;
- memória do worker;
- número de páginas com Form Parser;
- erros em documentos grandes.

O worker está configurado inicialmente com:

```text
4 CPU
8 GiB RAM
6 horas de timeout
```

Isso pode ser reduzido depois de medir o consumo real.

## 33. Concorrência

Nesta versão cada PDF finalizado pode iniciar uma execução independente do Cloud Run Job.

Para um primeiro ambiente de produção controlado, não libere centenas de uploads simultâneos sem antes observar quotas e custos.

Se a necessidade for processar lotes muito grandes simultaneamente, a próxima evolução recomendada é inserir uma fila explícita (Cloud Tasks/Workflows ou controlador de concorrência) com limite configurável de jobs ativos.

---

# PARTE O — ATUALIZAR O SISTEMA

Depois de alterar código Python:

```bash
./infra/deploy.sh
```

O script reconstrói as imagens e atualiza os recursos existentes.

Para mudanças somente no frontend, basta atualizar os arquivos do GitHub Pages; não é necessário redeploy do Cloud Run.

---

# Documentação oficial útil

Cloud Storage resumable uploads:
https://cloud.google.com/storage/docs/resumable-uploads

Cloud Storage CORS:
https://cloud.google.com/storage/docs/using-cors

Eventarc + Cloud Storage:
https://cloud.google.com/eventarc/docs/run/route-trigger-cloud-storage

Cloud Run Jobs:
https://cloud.google.com/run/docs/execute/jobs

Firebase Authentication Web:
https://firebase.google.com/docs/auth/web/start

Firestore:
https://cloud.google.com/firestore/docs

Document AI:
https://cloud.google.com/document-ai/docs
