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
cd cognotxt_gcp
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
BUCKET_NAME=meu-projeto-google-cliente-cognotxt
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
meu-projeto-google-cliente-cognotxt
```

já existir, use algo mais específico, por exemplo:

```text
cognotxt-meu-projeto-cliente-2026
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


================= EXECUÇÃO  =============================================================================

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ ./infra/deploy.sh 

== Projeto ==
Updated property [core/project].
Updated property [run/region].

== APIs ==
Operation "operations/acf.p2-940153605624-84e9657a-0f5e-4dac-b7a2-530f63d36640" finished successfully.

== Service Accounts ==
Created service account [cognotxt-api].
Service account email: cognotxt-api@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-dispatcher].
Service account email: cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-worker].
Service account email: cognotxt-worker@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-eventarc].
Service account email: cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com

== IAM de projeto ==
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ ./infra/deploy.sh 

== Projeto ==
Updated property [core/project].
Updated property [run/region].

== APIs ==
Operation "operations/acf.p2-940153605624-84e9657a-0f5e-4dac-b7a2-530f63d36640" finished successfully.

== Service Accounts ==
Created service account [cognotxt-api].
Service account email: cognotxt-api@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-dispatcher].
Service account email: cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-worker].
Service account email: cognotxt-worker@grafemapdf.iam.gserviceaccount.com
Created service account [cognotxt-eventarc].
Service account email: cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com

== IAM de projeto ==
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mSV9Is=
version: 1
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mS3-BM=
version: 1
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mTZQKM=
version: 1
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mT-Eyw=
version: 1
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mUdxKU=
version: 1
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com
  role: roles/eventarc.eventReceiver
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0mU9fRg=
version: 1
Updated IAM policy for serviceAccount [cognotxt-api@grafemapdf.iam.gserviceaccount.com].
bindings:
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
etag: BwZd0mVYNTs=
version: 1

== Bucket ==
Creating gs://grafemapdf-anater-cognotxt/...
Updating gs://grafemapdf-anater-cognotxt/...                                                                                                                                                                                                                   
  Completed 1                                                                                                                                                                                                                                                  
bindings:
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyBucketOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyBucketReader
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyObjectOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyObjectReader
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectCreator
etag: CAM=
kind: storage#policy
resourceId: projects/_/buckets/grafemapdf-anater-cognotxt
version: 1
bindings:
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyBucketOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyBucketReader
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyObjectOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyObjectReader
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectCreator
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectViewer
etag: CAQ=
kind: storage#policy
resourceId: projects/_/buckets/grafemapdf-anater-cognotxt
version: 1
bindings:
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyBucketOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyBucketReader
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyObjectOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyObjectReader
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectCreator
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectViewer
etag: CAU=
kind: storage#policy
resourceId: projects/_/buckets/grafemapdf-anater-cognotxt
version: 1
bindings:
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyBucketOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyBucketReader
- members:
  - projectEditor:grafemapdf
  - projectOwner:grafemapdf
  role: roles/storage.legacyObjectOwner
- members:
  - projectViewer:grafemapdf
  role: roles/storage.legacyObjectReader
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectCreator
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectViewer
etag: CAY=
kind: storage#policy
resourceId: projects/_/buckets/grafemapdf-anater-cognotxt
version: 1

== Artifact Registry ==
Create request issued for: [cognotxt]
Waiting for operation [projects/grafemapdf/locations/us-central1/operations/403cc485-719f-4ea0-a4bf-fc6cb20a5023] to complete...done.                                                                                                                          
Created repository [cognotxt].

== Build das imagens ==
Creating temporary archive of 3 file(s) totalling 6.1 KiB before compression.
Uploading tarball of [/home/arquitetura_joel/cognotxt_gcp/api] to [gs://grafemapdf_cloudbuild/source/1792008117.581934-78affb59c2e447ff887c08847ec6a7df.tgz]
ERROR: (gcloud.builds.submit) PERMISSION_DENIED: The caller does not have permission. This command is authenticated as arquitetura.joel@gmail.com which is the active account specified by the [core/account] property


=================================SOLUÇÃO ========================================================================


O erro está no usuário ativo:
arquitetura.joel@gmail.com

Ele conseguiu criar o Artifact Registry, mas não tem permissão para executar builds no Cloud Build.
A correção mínima é dar a esse usuário o papel:
Cloud Build Editor
roles/cloudbuild.builds.editor

Esse papel contém cloudbuild.builds.create, que é a permissão exigida pelo gcloud builds submit. Google Cloud Documentation
No Cloud Shell, execute com uma conta que tenha permissão de administrar IAM no projeto:
gcloud projects add-iam-policy-binding grafemapdf \
  --member="user:arquitetura.joel@gmail.com" \
  --role="roles/cloudbuild.builds.editor"

Depois confirme:
gcloud projects get-iam-policy grafemapdf \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:arquitetura.joel@gmail.com" \
  --format="table(bindings.role)"

Você deve ver algo contendo:
roles/cloudbuild.builds.editor


============================EXECUTADO=======================================================================================
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud projects add-iam-policy-binding grafemapdf \
  --member="user:arquitetura.joel@gmail.com" \
  --role="roles/cloudbuild.builds.editor"
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:service-940153605624@gcp-sa-artifactregistry.iam.gserviceaccount.com
  role: roles/artifactregistry.serviceAgent
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/cloudbuild.builds.editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com
  role: roles/eventarc.eventReceiver
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0nmq1cM=
version: 1
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud projects add-iam-policy-binding grafemapdf \
  --member="user:arquitetura.joel@gmail.com" \
  --role="roles/cloudbuild.builds.editor"
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:service-940153605624@gcp-sa-artifactregistry.iam.gserviceaccount.com
  role: roles/artifactregistry.serviceAgent
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/cloudbuild.builds.editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com
  role: roles/eventarc.eventReceiver
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0oTBbVA=
version: 1
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
==================================================================================================



 
Depois teste somente o build da API, antes de executar o script inteiro:
cd ~/cognotxt_gcp

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud builds submit ./api \
  --tag us-central1-docker.pkg.dev/grafemapdf/cognotxt/api:latest \
  --project grafemapdf



=================== ERRO DE EXECUÇÃO ======================================================================================

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$  gcloud builds submit ./api \
  --tag us-central1-docker.pkg.dev/grafemapdf/cognotxt/api:latest \
  --project grafemapdf
Creating temporary archive of 3 file(s) totalling 6.1 KiB before compression.
Uploading tarball of [./api] to [gs://grafemapdf_cloudbuild/source/1792008677.760632-4a294b60c210425facac69ed9ee1bcf9.tgz]
Created [https://cloudbuild.googleapis.com/v1/projects/grafemapdf/locations/global/builds/ae37bb5b-807b-431f-ba9e-976839901ba2].
Logs are available at [ https://console.cloud.google.com/cloud-build/builds/ae37bb5b-807b-431f-ba9e-976839901ba2?project=940153605624 ].
Waiting for build to complete. Polling interval: 1 second(s).
--------------------------------------------------------------------------------------------------------------------- REMOTE BUILD OUTPUT ----------------------------------------------------------------------------------------------------------------------
starting build "ae37bb5b-807b-431f-ba9e-976839901ba2"

FETCHSOURCE
Fetching storage object: gs://grafemapdf_cloudbuild/source/1792008677.760632-4a294b60c210425facac69ed9ee1bcf9.tgz#1792008678011088
Copying gs://grafemapdf_cloudbuild/source/1792008677.760632-4a294b60c210425facac69ed9ee1bcf9.tgz#1792008678011088...
/ [1 files][  2.8 KiB/  2.8 KiB]                                                
Operation completed over 1 objects/2.8 KiB.
BUILD
Already have image (with digest): gcr.io/cloud-builders/gcb-internal
DEPRECATED: The legacy builder is deprecated and will be removed in a future release.
            Install the buildx component to build images with BuildKit:
            https://docs.docker.com/go/buildx/

Sending build context to Docker daemon  9.728kB
Step 1/7 : FROM python:3.12-slim
3.12-slim: Pulling from library/python
ecc510c1e359: Pulling fs layer
75b6a36c64a1: Pulling fs layer
6912e23eb445: Pulling fs layer
bbc5a1223747: Pulling fs layer
bbc5a1223747: Verifying Checksum
bbc5a1223747: Download complete
75b6a36c64a1: Verifying Checksum
75b6a36c64a1: Download complete
6912e23eb445: Verifying Checksum
6912e23eb445: Download complete
ecc510c1e359: Verifying Checksum
ecc510c1e359: Download complete
ecc510c1e359: Pull complete
75b6a36c64a1: Pull complete
6912e23eb445: Pull complete
bbc5a1223747: Pull complete
Digest: sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
Status: Downloaded newer image for python:3.12-slim
 df18428df8a0
Step 2/7 : ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
 Running in 0092dbafa526
Removing intermediate container 0092dbafa526
 41d8ec60307d
Step 3/7 : WORKDIR /app
 Running in f994b422ec26
Removing intermediate container f994b422ec26
 ae8bbca9df23
Step 4/7 : COPY requirements.txt .
 29352f87732e
Step 5/7 : RUN pip install --no-cache-dir -r requirements.txt
 Running in 4a52ff30035c
Collecting fastapi==0.115.12 (from -r requirements.txt (line 1))
  Downloading fastapi-0.115.12-py3-none-any.whl.metadata (27 kB)
Collecting uvicorn==0.34.2 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading uvicorn-0.34.2-py3-none-any.whl.metadata (6.5 kB)
Collecting gunicorn==23.0.0 (from -r requirements.txt (line 3))
  Downloading gunicorn-23.0.0-py3-none-any.whl.metadata (4.4 kB)
Collecting google-cloud-storage==3.1.0 (from -r requirements.txt (line 4))
  Downloading google_cloud_storage-3.1.0-py2.py3-none-any.whl.metadata (12 kB)
Collecting google-cloud-firestore==2.20.2 (from -r requirements.txt (line 5))
  Downloading google_cloud_firestore-2.20.2-py3-none-any.whl.metadata (9.9 kB)
Collecting google-auth==2.40.3 (from -r requirements.txt (line 6))
  Downloading google_auth-2.40.3-py2.py3-none-any.whl.metadata (6.2 kB)
Collecting firebase-admin==7.0.0 (from -r requirements.txt (line 7))
  Downloading firebase_admin-7.0.0-py3-none-any.whl.metadata (1.7 kB)
Collecting pydantic==2.11.7 (from -r requirements.txt (line 8))
  Downloading pydantic-2.11.7-py3-none-any.whl.metadata (67 kB)
Collecting starlette<0.47.0,>=0.40.0 (from fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading starlette-0.46.2-py3-none-any.whl.metadata (6.2 kB)
Collecting typing-extensions>=4.8.0 (from fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading typing_extensions-4.16.0-py3-none-any.whl.metadata (3.3 kB)
Collecting click>=7.0 (from uvicorn==0.34.2->uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading click-8.5.0-py3-none-any.whl.metadata (2.6 kB)
Collecting h11>=0.8 (from uvicorn==0.34.2->uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
Collecting packaging (from gunicorn==23.0.0->-r requirements.txt (line 3))
  Downloading packaging-26.3-py3-none-any.whl.metadata (3.5 kB)
Collecting google-api-core<3.0.0dev,>=2.15.0 (from google-cloud-storage==3.1.0->-r requirements.txt (line 4))
  Downloading google_api_core-2.42.0-py3-none-any.whl.metadata (3.2 kB)
Collecting google-cloud-core<3.0dev,>=2.4.2 (from google-cloud-storage==3.1.0->-r requirements.txt (line 4))
  Downloading google_cloud_core-2.8.0-py3-none-any.whl.metadata (2.9 kB)
Collecting google-resumable-media>=2.7.2 (from google-cloud-storage==3.1.0->-r requirements.txt (line 4))
  Downloading google_resumable_media-2.11.0-py3-none-any.whl.metadata (2.3 kB)
Collecting requests<3.0.0dev,>=2.18.0 (from google-cloud-storage==3.1.0->-r requirements.txt (line 4))
  Downloading requests-2.34.2-py3-none-any.whl.metadata (4.8 kB)
Collecting google-crc32c<2.0dev,>=1.0 (from google-cloud-storage==3.1.0->-r requirements.txt (line 4))
  Downloading google_crc32c-1.9.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.2 kB)
Collecting proto-plus<2.0.0,>=1.22.0 (from google-cloud-firestore==2.20.2->-r requirements.txt (line 5))
  Downloading proto_plus-1.29.0-py3-none-any.whl.metadata (2.2 kB)
Collecting protobuf!=3.20.0,!=3.20.1,!=4.21.0,!=4.21.1,!=4.21.2,!=4.21.3,!=4.21.4,!=4.21.5,<7.0.0dev,>=3.20.2 (from google-cloud-firestore==2.20.2->-r requirements.txt (line 5))
  Downloading protobuf-6.33.6-cp39-abi3-manylinux2014_x86_64.whl.metadata (593 bytes)
Collecting cachetools<6.0,>=2.0.0 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading cachetools-5.5.2-py3-none-any.whl.metadata (5.4 kB)
Collecting pyasn1-modules>=0.2.1 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading pyasn1_modules-0.4.2-py3-none-any.whl.metadata (3.5 kB)
Collecting rsa<5,>=3.1.4 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading rsa-4.9.1-py3-none-any.whl.metadata (5.6 kB)
Collecting cachecontrol>=0.14.3 (from firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading cachecontrol-0.14.4-py3-none-any.whl.metadata (3.1 kB)
INFO: pip is looking at multiple versions of firebase-admin to determine which version is compatible with other requirements. This could take a while.
ERROR: Cannot install -r requirements.txt (line 7) and google-cloud-firestore==2.20.2 because these package versions have conflicting dependencies.

The conflict is caused by:
    The user requested google-cloud-firestore==2.20.2
    firebase-admin 7.0.0 depends on google-cloud-firestore>=2.21.0; platform_python_implementation != "PyPy"


To fix this you could try to:
1. loosen the range of package versions you've specified
2. remove package versions to allow pip to attempt to solve the dependency conflict


[notice] A new release of pip is available: 25.0.1 -> 26.2.1
[notice] To update, run: pip install --upgrade pip
ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts
The command '/bin/sh -c pip install --no-cache-dir -r requirements.txt' returned a non-zero code: 1
ERROR
ERROR: build step 0 "gcr.io/cloud-builders/gcb-internal" failed: step exited with non-zero status: 1

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

BUILD FAILURE: Build step failure: build step 0 "gcr.io/cloud-builders/gcb-internal" failed: step exited with non-zero status: 1
ERROR: (gcloud.builds.submit) build ae37bb5b-807b-431f-ba9e-976839901ba2 completed with status "FAILURE"

=================================================== CORREÇÃO ==================================================================================================
O erro agora é somente de dependências Python incompatíveis.
O firebase-admin==7.0.0 exige:
google-cloud-firestore >= 2.21.0
google-cloud-storage >= 3.1.1

e o pacote anterior estava fixando versões menores. Isso é confirmado nas notas de release do Firebase Admin Python. firebase.google.com
Corrigi o projeto.
cognotxt_cloud_producao_corrigido.zip
Se preferir corrigir diretamente no Cloud Shell, edite:
nano api/requirements.txt

e deixe assim:
fastapi==0.115.12
uvicorn[standard]==0.34.2
gunicorn==23.0.0
google-cloud-storage==3.1.1
google-cloud-firestore==2.21.0
google-auth==2.40.3
firebase-admin==7.0.0
pydantic==2.11.7

Depois rode novamente apenas o build da API:
gcloud builds submit ./api \
  --tag us-central1-docker.pkg.dev/grafemapdf/cognotxt/api:latest \
  --project grafemapdf

Se aparecer:
SUCCESS

então rode novamente:
./infra/deploy.sh

Também alinhei no pacote corrigido:
dispatcher:
google-cloud-firestore==2.21.0

worker:
google-cloud-storage==3.1.1
google-cloud-firestore==2.21.0

Assim evitamos inconsistências entre as três imagens Docker.
O erro que você teve não tem relação com GCP, IAM ou Docker; foi exclusivamente o resolvedor do pip recusando versões incompatíveis. A próxima tentativa já deve ultrapassar essa etapa.

=====================================================================================================================================================





=====================================================================================================================================================

Se funcionar, você verá algo parecido com:
BUILD
...
PUSH
...
SUCCESS

Pode aparecer um segundo erro
Depois de autorizar seu usuário, o Cloud Build pode conseguir iniciar o build mas falhar ao enviar a imagem para o Artifact Registry.
Nesse caso, a conta de serviço usada pelo Cloud Build precisa ter:
Artifact Registry Writer
roles/artifactregistry.writer

O Google recomenda esse papel para a service account que executa builds quando ela precisa publicar imagens no Artifact Registry. Google Cloud Documentation
Primeiro descubra o número do projeto:
gcloud projects describe grafemapdf \
  --format="value(projectNumber)"

Suponha que retorne:
123456789012

Confira qual conta o Cloud Build está utilizando:
gcloud builds get-default-service-account \
  --project=grafemapdf

Se retornar, por exemplo:
123456789012-compute@developer.gserviceaccount.com

dê a ela permissão:
gcloud projects add-iam-policy-binding grafemapdf \
  --member="serviceAccount:123456789012-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

Em projetos/configurações que usam a service account legada, pode aparecer:
123456789012@cloudbuild.gserviceaccount.com

Nesse caso use exatamente a conta retornada pelo comando anterior. Não assuma o nome.
Sequência que eu recomendo agora
Execute:
gcloud config set project grafemapdf

gcloud auth list

Confirme que aparece:
arquitetura.joel@gmail.com  ACTIVE

Depois:
gcloud projects add-iam-policy-binding grafemapdf \
  --member="user:arquitetura.joel@gmail.com" \
  --role="roles/cloudbuild.builds.editor"

E teste:
gcloud builds submit ./api \
  --tag us-central1-docker.pkg.dev/grafemapdf/cognotxt/api:latest

Se esse comando terminar com SUCCESS, então você pode voltar a executar o nosso:
./infra/deploy.sh

O ponto importante é: não dê Owner só para resolver isso. Cloud Build Editor para seu usuário é suficiente para iniciar o build,
e Artifact Registry Writer deve ficar na service account do build quando necessário. Isso mantém o IAM bem mais seguro.








==========================================================================================================


arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud projects add-iam-policy-binding grafemapdf \
  --member="user:arquitetura.joel@gmail.com" \
  --role="roles/cloudbuild.builds.editor"
Updated IAM policy for project [grafemapdf].
bindings:
- members:
  - serviceAccount:service-940153605624@gcp-sa-artifactregistry.iam.gserviceaccount.com
  role: roles/artifactregistry.serviceAgent
- members:
  - serviceAccount:940153605624@cloudbuild.gserviceaccount.com
  role: roles/cloudbuild.builds.builder
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/cloudbuild.builds.editor
- members:
  - serviceAccount:service-940153605624@gcp-sa-cloudbuild.iam.gserviceaccount.com
  role: roles/cloudbuild.serviceAgent
- members:
  - serviceAccount:service-940153605624@containerregistry.iam.gserviceaccount.com
  role: roles/containerregistry.ServiceAgent
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/datastore.user
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.apiUser
- members:
  - serviceAccount:api-doc-grafemapdf@grafemapdf.iam.gserviceaccount.com
  role: roles/documentai.viewer
- members:
  - serviceAccount:service-940153605624@gcp-sa-prod-dai-core.iam.gserviceaccount.com
  role: roles/documentaicore.serviceAgent
- members:
  - serviceAccount:940153605624-compute@developer.gserviceaccount.com
  role: roles/editor
- members:
  - serviceAccount:cognotxt-eventarc@grafemapdf.iam.gserviceaccount.com
  role: roles/eventarc.eventReceiver
- members:
  - serviceAccount:service-940153605624@gcp-sa-firebase.iam.gserviceaccount.com
  role: roles/firebase.managementServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebase.sdkAdminServiceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/firebaseauth.admin
- members:
  - serviceAccount:service-940153605624@firebase-rules.iam.gserviceaccount.com
  role: roles/firebaserules.system
- members:
  - serviceAccount:service-940153605624@gcp-sa-firestore.iam.gserviceaccount.com
  role: roles/firestore.serviceAgent
- members:
  - serviceAccount:firebase-adminsdk-fbsvc@grafemapdf.iam.gserviceaccount.com
  role: roles/iam.serviceAccountTokenCreator
- members:
  - user:arquitetura.joel@gmail.com
  role: roles/owner
- members:
  - serviceAccount:cognotxt-dispatcher@grafemapdf.iam.gserviceaccount.com
  role: roles/run.developer
- members:
  - serviceAccount:service-940153605624@serverless-robot-prod.iam.gserviceaccount.com
  role: roles/run.serviceAgent
etag: BwZd0nmq1cM=
version: 1
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
- 










































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
