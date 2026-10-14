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

=============================CORREÇÃO  ========================================================================================================

feito ajuste no requirements.txt



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




 - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectCreator
- members:
  - serviceAccount:cognotxt-api@grafemapdf.iam.gserviceaccount.com
  - serviceAccount:cognotxt-worker@grafemapdf.iam.gserviceaccount.com
  role: roles/storage.objectViewer
etag: CAs=
kind: storage#policy
resourceId: projects/_/buckets/grafemapdf-anater-cognotxt
version: 1

== Artifact Registry ==

== Build das imagens ==
Creating temporary archive of 3 file(s) totalling 6.1 KiB before compression.
Uploading tarball of [/home/arquitetura_joel/cognotxt_gcp/api] to [gs://grafemapdf_cloudbuild/source/1792010944.236616-b11896abd55d4179a9cb999a9f43df3e.tgz]
Created [https://cloudbuild.googleapis.com/v1/projects/grafemapdf/locations/global/builds/101f520d-201b-471a-b238-846234061d49].
Logs are available at [ https://console.cloud.google.com/cloud-build/builds/101f520d-201b-471a-b238-846234061d49?project=940153605624 ].
Waiting for build to complete. Polling interval: 1 second(s).
--------------------------------------------------------------------------------------------------------------------- REMOTE BUILD OUTPUT ----------------------------------------------------------------------------------------------------------------------
starting build "101f520d-201b-471a-b238-846234061d49"

FETCHSOURCE
Fetching storage object: gs://grafemapdf_cloudbuild/source/1792010944.236616-b11896abd55d4179a9cb999a9f43df3e.tgz#1792010944454724
Copying gs://grafemapdf_cloudbuild/source/1792010944.236616-b11896abd55d4179a9cb999a9f43df3e.tgz#1792010944454724...
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
ecc510c1e359: Already exists
75b6a36c64a1: Pulling fs layer
6912e23eb445: Pulling fs layer
bbc5a1223747: Pulling fs layer
bbc5a1223747: Verifying Checksum
bbc5a1223747: Download complete
6912e23eb445: Verifying Checksum
6912e23eb445: Download complete
75b6a36c64a1: Verifying Checksum
75b6a36c64a1: Download complete
75b6a36c64a1: Pull complete
6912e23eb445: Pull complete
bbc5a1223747: Pull complete
Digest: sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
Status: Downloaded newer image for python:3.12-slim
 df18428df8a0
Step 2/7 : ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
 Running in 6914d86ea2c7
Removing intermediate container 6914d86ea2c7
 e5bd4c4687ba
Step 3/7 : WORKDIR /app
 Running in c90eb9927912
Removing intermediate container c90eb9927912
 4af4b0c7bc1e
Step 4/7 : COPY requirements.txt .
 6076fa55510b
Step 5/7 : RUN pip install --no-cache-dir -r requirements.txt
 Running in e454d94e2366
Collecting fastapi==0.115.12 (from -r requirements.txt (line 1))
  Downloading fastapi-0.115.12-py3-none-any.whl.metadata (27 kB)
Collecting uvicorn==0.34.2 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading uvicorn-0.34.2-py3-none-any.whl.metadata (6.5 kB)
Collecting gunicorn==23.0.0 (from -r requirements.txt (line 3))
  Downloading gunicorn-23.0.0-py3-none-any.whl.metadata (4.4 kB)
Collecting google-cloud-storage==3.1.1 (from -r requirements.txt (line 4))
  Downloading google_cloud_storage-3.1.1-py3-none-any.whl.metadata (13 kB)
Collecting google-cloud-firestore==2.21.0 (from -r requirements.txt (line 5))
  Downloading google_cloud_firestore-2.21.0-py3-none-any.whl.metadata (9.9 kB)
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
Collecting google-api-core<3.0.0,>=2.15.0 (from google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading google_api_core-2.42.0-py3-none-any.whl.metadata (3.2 kB)
Collecting google-cloud-core<3.0.0,>=2.4.2 (from google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading google_cloud_core-2.8.0-py3-none-any.whl.metadata (2.9 kB)
Collecting google-resumable-media<3.0.0,>=2.7.2 (from google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading google_resumable_media-2.11.0-py3-none-any.whl.metadata (2.3 kB)
Collecting requests<3.0.0,>=2.22.0 (from google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading requests-2.34.2-py3-none-any.whl.metadata (4.8 kB)
Collecting google-crc32c<2.0.0,>=1.1.3 (from google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading google_crc32c-1.9.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.2 kB)
Collecting proto-plus<2.0.0,>=1.22.0 (from google-cloud-firestore==2.21.0->-r requirements.txt (line 5))
  Downloading proto_plus-1.29.0-py3-none-any.whl.metadata (2.2 kB)
Collecting protobuf!=3.20.0,!=3.20.1,!=4.21.0,!=4.21.1,!=4.21.2,!=4.21.3,!=4.21.4,!=4.21.5,<7.0.0dev,>=3.20.2 (from google-cloud-firestore==2.21.0->-r requirements.txt (line 5))
  Downloading protobuf-6.33.6-cp39-abi3-manylinux2014_x86_64.whl.metadata (593 bytes)
Collecting cachetools<6.0,>=2.0.0 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading cachetools-5.5.2-py3-none-any.whl.metadata (5.4 kB)
Collecting pyasn1-modules>=0.2.1 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading pyasn1_modules-0.4.2-py3-none-any.whl.metadata (3.5 kB)
Collecting rsa<5,>=3.1.4 (from google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading rsa-4.9.1-py3-none-any.whl.metadata (5.6 kB)
Collecting cachecontrol>=0.14.3 (from firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading cachecontrol-0.14.4-py3-none-any.whl.metadata (3.1 kB)
Collecting pyjwt>=2.10.1 (from pyjwt[crypto]>=2.10.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading pyjwt-2.15.1-py3-none-any.whl.metadata (3.5 kB)
Collecting httpx==0.28.1 (from httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
Collecting annotated-types>=0.6.0 (from pydantic==2.11.7->-r requirements.txt (line 8))
  Downloading annotated_types-0.8.0-py3-none-any.whl.metadata (15 kB)
Collecting pydantic-core==2.33.2 (from pydantic==2.11.7->-r requirements.txt (line 8))
  Downloading pydantic_core-2.33.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (6.8 kB)
Collecting typing-inspection>=0.4.0 (from pydantic==2.11.7->-r requirements.txt (line 8))
  Downloading typing_inspection-0.4.4-py3-none-any.whl.metadata (2.6 kB)
Collecting httptools>=0.6.3 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading httptools-0.9.0-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (3.5 kB)
Collecting python-dotenv>=0.13 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading python_dotenv-1.2.4-py3-none-any.whl.metadata (29 kB)
Collecting pyyaml>=5.1 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.4 kB)
Collecting uvloop!=0.15.0,!=0.15.1,>=0.14.0 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (5.1 kB)
Collecting watchfiles>=0.13 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (4.9 kB)
Collecting websockets>=10.4 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading websockets-17.2-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (6.3 kB)
Collecting anyio (from httpx==0.28.1->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading anyio-4.15.1-py3-none-any.whl.metadata (4.7 kB)
Collecting certifi (from httpx==0.28.1->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading certifi-2026.7.22-py3-none-any.whl.metadata (2.5 kB)
Collecting httpcore==1.* (from httpx==0.28.1->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
Collecting idna (from httpx==0.28.1->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading idna-3.20-py3-none-any.whl.metadata (7.2 kB)
Collecting h2<5,>=3 (from httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading h2-4.4.1-py3-none-any.whl.metadata (3.8 kB)
Collecting msgpack<2.0.0,>=0.5.2 (from cachecontrol>=0.14.3->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading msgpack-1.2.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (8.3 kB)
Collecting googleapis-common-protos<2.0.0,>=1.69.2 (from google-api-core<3.0.0,>=2.15.0->google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading googleapis_common_protos-1.75.5-py3-none-any.whl.metadata (8.5 kB)
Collecting opentelemetry-api<2.0.0,>=1.44.0 (from google-api-core<3.0.0,>=2.15.0->google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading opentelemetry_api-1.45.1-py3-none-any.whl.metadata (1.4 kB)
Collecting grpcio<2.0.0,>=1.59.0 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 5))
  Downloading grpcio-1.84.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (3.8 kB)
Collecting grpcio-status<2.0.0,>=1.59.0 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 5))
  Downloading grpcio_status-1.84.0-py3-none-any.whl.metadata (1.3 kB)
Collecting pyasn1<0.7.0,>=0.6.1 (from pyasn1-modules>=0.2.1->google-auth==2.40.3->-r requirements.txt (line 6))
  Downloading pyasn1-0.6.4-py3-none-any.whl.metadata (8.4 kB)
Collecting cryptography>=3.4.0 (from pyjwt[crypto]>=2.10.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl.metadata (4.4 kB)
Collecting charset_normalizer<4,>=2 (from requests<3.0.0,>=2.22.0->google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (46 kB)
Collecting urllib3<3,>=1.26 (from requests<3.0.0,>=2.22.0->google-cloud-storage==3.1.1->-r requirements.txt (line 4))
  Downloading urllib3-2.8.0-py3-none-any.whl.metadata (7.4 kB)
Collecting cffi>=2.0.0 (from cryptography>=3.4.0->pyjwt[crypto]>=2.10.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading cffi-2.1.1-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.5 kB)
Collecting hyperframe<7,>=6.1 (from h2<5,>=3->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading hyperframe-6.1.0-py3-none-any.whl.metadata (4.3 kB)
Collecting hpack<5,>=4.2 (from h2<5,>=3->httpx[http2]==0.28.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading hpack-4.2.0-py3-none-any.whl.metadata (3.3 kB)
Collecting pycparser (from cffi>=2.0.0->cryptography>=3.4.0->pyjwt[crypto]>=2.10.1->firebase-admin==7.0.0->-r requirements.txt (line 7))
  Downloading pycparser-3.11-py3-none-any.whl.metadata (8.2 kB)
Downloading fastapi-0.115.12-py3-none-any.whl (95 kB)
Downloading uvicorn-0.34.2-py3-none-any.whl (62 kB)
Downloading gunicorn-23.0.0-py3-none-any.whl (85 kB)
Downloading google_cloud_storage-3.1.1-py3-none-any.whl (175 kB)
Downloading google_cloud_firestore-2.21.0-py3-none-any.whl (368 kB)
Downloading google_auth-2.40.3-py2.py3-none-any.whl (216 kB)
Downloading firebase_admin-7.0.0-py3-none-any.whl (136 kB)
Downloading pydantic-2.11.7-py3-none-any.whl (444 kB)
Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
Downloading pydantic_core-2.33.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (2.0 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.0/2.0 MB 314.9 MB/s eta 0:00:00
Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
Downloading annotated_types-0.8.0-py3-none-any.whl (13 kB)
Downloading cachecontrol-0.14.4-py3-none-any.whl (22 kB)
Downloading cachetools-5.5.2-py3-none-any.whl (10 kB)
Downloading click-8.5.0-py3-none-any.whl (125 kB)
Downloading google_api_core-2.42.0-py3-none-any.whl (221 kB)
Downloading google_cloud_core-2.8.0-py3-none-any.whl (31 kB)
Downloading google_crc32c-1.9.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (36 kB)
Downloading google_resumable_media-2.11.0-py3-none-any.whl (81 kB)
Downloading h11-0.16.0-py3-none-any.whl (37 kB)
Downloading httptools-0.9.0-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (552 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 552.8/552.8 kB 51.6 MB/s eta 0:00:00
Downloading proto_plus-1.29.0-py3-none-any.whl (50 kB)
Downloading protobuf-6.33.6-cp39-abi3-manylinux2014_x86_64.whl (323 kB)
Downloading pyasn1_modules-0.4.2-py3-none-any.whl (181 kB)
Downloading pyjwt-2.15.1-py3-none-any.whl (33 kB)
Downloading python_dotenv-1.2.4-py3-none-any.whl (23 kB)
Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (807 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 807.9/807.9 kB 525.7 MB/s eta 0:00:00
Downloading requests-2.34.2-py3-none-any.whl (73 kB)
Downloading rsa-4.9.1-py3-none-any.whl (34 kB)
Downloading starlette-0.46.2-py3-none-any.whl (72 kB)
Downloading typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Downloading typing_inspection-0.4.4-py3-none-any.whl (14 kB)
Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (4.5 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.5/4.5 MB 224.9 MB/s eta 0:00:00
Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (458 kB)
Downloading websockets-17.2-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (225 kB)
Downloading packaging-26.3-py3-none-any.whl (129 kB)
Downloading anyio-4.15.1-py3-none-any.whl (132 kB)
Downloading certifi-2026.7.22-py3-none-any.whl (136 kB)
Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (257 kB)
Downloading cryptography-50.0.2-cp311-abi3-manylinux_2_34_x86_64.whl (4.8 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.8/4.8 MB 220.2 MB/s eta 0:00:00
Downloading googleapis_common_protos-1.75.5-py3-none-any.whl (307 kB)
Downloading grpcio-1.84.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (7.2 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 7.2/7.2 MB 152.3 MB/s eta 0:00:00
Downloading grpcio_status-1.84.0-py3-none-any.whl (14 kB)
Downloading h2-4.4.1-py3-none-any.whl (62 kB)
Downloading idna-3.20-py3-none-any.whl (69 kB)
Downloading msgpack-1.2.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (472 kB)
Downloading opentelemetry_api-1.45.1-py3-none-any.whl (60 kB)
Downloading pyasn1-0.6.4-py3-none-any.whl (84 kB)
Downloading urllib3-2.8.0-py3-none-any.whl (135 kB)
Downloading cffi-2.1.1-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (221 kB)
Downloading hpack-4.2.0-py3-none-any.whl (34 kB)
Downloading hyperframe-6.1.0-py3-none-any.whl (13 kB)
Downloading pycparser-3.11-py3-none-any.whl (51 kB)
Installing collected packages: websockets, uvloop, urllib3, typing-extensions, pyyaml, python-dotenv, pyjwt, pycparser, pyasn1, protobuf, packaging, msgpack, idna, hyperframe, httptools, hpack, h11, google-crc32c, click, charset_normalizer, certifi, cachetools, annotated-types, uvicorn, typing-inspection, rsa, requests, pydantic-core, pyasn1-modules, proto-plus, opentelemetry-api, httpcore, h2, gunicorn, grpcio, googleapis-common-protos, google-resumable-media, cffi, anyio, watchfiles, starlette, pydantic, httpx, grpcio-status, google-auth, cryptography, cachecontrol, google-api-core, fastapi, google-cloud-core, google-cloud-storage, google-cloud-firestore, firebase-admin
Successfully installed annotated-types-0.8.0 anyio-4.15.1 cachecontrol-0.14.4 cachetools-5.5.2 certifi-2026.7.22 cffi-2.1.1 charset_normalizer-3.5.2 click-8.5.0 cryptography-50.0.2 fastapi-0.115.12 firebase-admin-7.0.0 google-api-core-2.42.0 google-auth-2.40.3 google-cloud-core-2.8.0 google-cloud-firestore-2.21.0 google-cloud-storage-3.1.1 google-crc32c-1.9.0 google-resumable-media-2.11.0 googleapis-common-protos-1.75.5 grpcio-1.84.0 grpcio-status-1.84.0 gunicorn-23.0.0 h11-0.16.0 h2-4.4.1 hpack-4.2.0 httpcore-1.0.9 httptools-0.9.0 httpx-0.28.1 hyperframe-6.1.0 idna-3.20 msgpack-1.2.3 opentelemetry-api-1.45.1 packaging-26.3 proto-plus-1.29.0 protobuf-6.33.6 pyasn1-0.6.4 pyasn1-modules-0.4.2 pycparser-3.11 pydantic-2.11.7 pydantic-core-2.33.2 pyjwt-2.15.1 python-dotenv-1.2.4 pyyaml-6.0.3 requests-2.34.2 rsa-4.9.1 starlette-0.46.2 typing-extensions-4.16.0 typing-inspection-0.4.4 urllib3-2.8.0 uvicorn-0.34.2 uvloop-0.23.0 watchfiles-1.3.0 websockets-17.2
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.

[notice] A new release of pip is available: 25.0.1 -> 26.2.1
[notice] To update, run: pip install --upgrade pip
Removing intermediate container e454d94e2366
 7c013b443afe
Step 6/7 : COPY main.py .
 8e03989f83d7
Step 7/7 : CMD exec gunicorn -k uvicorn.workers.UvicornWorker -b :${PORT:-8080} --workers 2 --threads 4 --timeout 0 main:app
 Running in 5bbb6a1b8b82
Removing intermediate container 5bbb6a1b8b82
 f398a820f34c
Successfully built f398a820f34c
Successfully tagged us-central1-docker.pkg.dev/grafemapdf/cognotxt/api:latest

--------------------------------------------------------------------------------------------------------------------- REMOTE BUILD OUTPUT ----------------------------------------------------------------------------------------------------------------------
starting build "0730dfeb-b49b-4cd8-8b02-97be6c885863"

FETCHSOURCE
Fetching storage object: gs://grafemapdf_cloudbuild/source/1792011003.080343-0ec41ebf4de04be78383092cc3641074.tgz#1792011003300962
Copying gs://grafemapdf_cloudbuild/source/1792011003.080343-0ec41ebf4de04be78383092cc3641074.tgz#1792011003300962...
/ [1 files][  1.7 KiB/  1.7 KiB]                                                
Operation completed over 1 objects/1.7 KiB.
BUILD
Already have image (with digest): gcr.io/cloud-builders/gcb-internal
DEPRECATED: The legacy builder is deprecated and will be removed in a future release.
            Install the buildx component to build images with BuildKit:
            https://docs.docker.com/go/buildx/

Sending build context to Docker daemon  7.168kB
Step 1/7 : FROM python:3.12-slim
3.12-slim: Pulling from library/python
ecc510c1e359: Pulling fs layer
75b6a36c64a1: Pulling fs layer
6912e23eb445: Pulling fs layer
bbc5a1223747: Pulling fs layer
bbc5a1223747: Verifying Checksum
bbc5a1223747: Download complete
75b6a36c64a1: Download complete
ecc510c1e359: Verifying Checksum
ecc510c1e359: Download complete
6912e23eb445: Verifying Checksum
6912e23eb445: Download complete
ecc510c1e359: Pull complete
75b6a36c64a1: Pull complete
6912e23eb445: Pull complete
bbc5a1223747: Pull complete
Digest: sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
Status: Downloaded newer image for python:3.12-slim
 df18428df8a0
Step 2/7 : ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
 Running in 1f24d6ddf809
Removing intermediate container 1f24d6ddf809
 cb76f5dc8ff2
Step 3/7 : WORKDIR /app
 Running in 12f59f5fc23a
Removing intermediate container 12f59f5fc23a
 fe33b8184f2e
Step 4/7 : COPY requirements.txt .
 401bb65588d9
Step 5/7 : RUN pip install --no-cache-dir -r requirements.txt
 Running in 20cb1864b703
Collecting fastapi==0.115.12 (from -r requirements.txt (line 1))
  Downloading fastapi-0.115.12-py3-none-any.whl.metadata (27 kB)
Collecting uvicorn==0.34.2 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading uvicorn-0.34.2-py3-none-any.whl.metadata (6.5 kB)
Collecting gunicorn==23.0.0 (from -r requirements.txt (line 3))
  Downloading gunicorn-23.0.0-py3-none-any.whl.metadata (4.4 kB)
Collecting google-cloud-firestore==2.21.0 (from -r requirements.txt (line 4))
  Downloading google_cloud_firestore-2.21.0-py3-none-any.whl.metadata (9.9 kB)
Collecting google-auth==2.40.3 (from -r requirements.txt (line 5))
  Downloading google_auth-2.40.3-py2.py3-none-any.whl.metadata (6.2 kB)
Collecting requests==2.32.4 (from -r requirements.txt (line 6))
  Downloading requests-2.32.4-py3-none-any.whl.metadata (4.9 kB)
Collecting starlette<0.47.0,>=0.40.0 (from fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading starlette-0.46.2-py3-none-any.whl.metadata (6.2 kB)
Collecting pydantic!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0,>=1.7.4 (from fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading pydantic-2.14.1-py3-none-any.whl.metadata (133 kB)
Collecting typing-extensions>=4.8.0 (from fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading typing_extensions-4.16.0-py3-none-any.whl.metadata (3.3 kB)
Collecting click>=7.0 (from uvicorn==0.34.2->uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading click-8.5.0-py3-none-any.whl.metadata (2.6 kB)
Collecting h11>=0.8 (from uvicorn==0.34.2->uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
Collecting packaging (from gunicorn==23.0.0->-r requirements.txt (line 3))
  Downloading packaging-26.3-py3-none-any.whl.metadata (3.5 kB)
Collecting google-api-core!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading google_api_core-2.42.0-py3-none-any.whl.metadata (3.2 kB)
Collecting google-cloud-core<3.0.0,>=1.4.1 (from google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading google_cloud_core-2.8.0-py3-none-any.whl.metadata (2.9 kB)
Collecting proto-plus<2.0.0,>=1.22.0 (from google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading proto_plus-1.29.0-py3-none-any.whl.metadata (2.2 kB)
Collecting protobuf!=3.20.0,!=3.20.1,!=4.21.0,!=4.21.1,!=4.21.2,!=4.21.3,!=4.21.4,!=4.21.5,<7.0.0dev,>=3.20.2 (from google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading protobuf-6.33.6-cp39-abi3-manylinux2014_x86_64.whl.metadata (593 bytes)
Collecting cachetools<6.0,>=2.0.0 (from google-auth==2.40.3->-r requirements.txt (line 5))
  Downloading cachetools-5.5.2-py3-none-any.whl.metadata (5.4 kB)
Collecting pyasn1-modules>=0.2.1 (from google-auth==2.40.3->-r requirements.txt (line 5))
  Downloading pyasn1_modules-0.4.2-py3-none-any.whl.metadata (3.5 kB)
Collecting rsa<5,>=3.1.4 (from google-auth==2.40.3->-r requirements.txt (line 5))
  Downloading rsa-4.9.1-py3-none-any.whl.metadata (5.6 kB)
Collecting charset_normalizer<4,>=2 (from requests==2.32.4->-r requirements.txt (line 6))
  Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (46 kB)
Collecting idna<4,>=2.5 (from requests==2.32.4->-r requirements.txt (line 6))
  Downloading idna-3.20-py3-none-any.whl.metadata (7.2 kB)
Collecting urllib3<3,>=1.21.1 (from requests==2.32.4->-r requirements.txt (line 6))
  Downloading urllib3-2.8.0-py3-none-any.whl.metadata (7.4 kB)
Collecting certifi>=2017.4.17 (from requests==2.32.4->-r requirements.txt (line 6))
  Downloading certifi-2026.7.22-py3-none-any.whl.metadata (2.5 kB)
Collecting httptools>=0.6.3 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading httptools-0.9.0-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (3.5 kB)
Collecting python-dotenv>=0.13 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading python_dotenv-1.2.4-py3-none-any.whl.metadata (29 kB)
Collecting pyyaml>=5.1 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.4 kB)
Collecting uvloop!=0.15.0,!=0.15.1,>=0.14.0 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (5.1 kB)
Collecting watchfiles>=0.13 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (4.9 kB)
Collecting websockets>=10.4 (from uvicorn[standard]==0.34.2->-r requirements.txt (line 2))
  Downloading websockets-17.2-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (6.3 kB)
Collecting googleapis-common-protos<2.0.0,>=1.69.2 (from google-api-core!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading googleapis_common_protos-1.75.5-py3-none-any.whl.metadata (8.5 kB)
INFO: pip is looking at multiple versions of google-api-core to determine which version is compatible with other requirements. This could take a while.
Collecting google-api-core!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading google_api_core-2.41.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.40.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.39.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.38.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.37.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.36.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.34.0-py3-none-any.whl.metadata (2.9 kB)
INFO: pip is still looking at multiple versions of google-api-core to determine which version is compatible with other requirements. This could take a while.
  Downloading google_api_core-2.33.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.32.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.31.0-py3-none-any.whl.metadata (3.2 kB)
  Downloading google_api_core-2.30.3-py3-none-any.whl.metadata (3.1 kB)
INFO: pip is looking at multiple versions of google-api-core[grpc] to determine which version is compatible with other requirements. This could take a while.
INFO: pip is still looking at multiple versions of google-api-core[grpc] to determine which version is compatible with other requirements. This could take a while.
Collecting grpcio<2.0.0,>=1.33.2 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading grpcio-1.84.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (3.8 kB)
Collecting grpcio-status<2.0.0,>=1.33.2 (from google-api-core[grpc]!=2.0.*,!=2.1.*,!=2.10.*,!=2.2.*,!=2.3.*,!=2.4.*,!=2.5.*,!=2.6.*,!=2.7.*,!=2.8.*,!=2.9.*,<3.0.0,>=1.34.0->google-cloud-firestore==2.21.0->-r requirements.txt (line 4))
  Downloading grpcio_status-1.84.0-py3-none-any.whl.metadata (1.3 kB)
Collecting pyasn1<0.7.0,>=0.6.1 (from pyasn1-modules>=0.2.1->google-auth==2.40.3->-r requirements.txt (line 5))
  Downloading pyasn1-0.6.4-py3-none-any.whl.metadata (8.4 kB)
Collecting annotated-types>=0.6.0 (from pydantic!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0,>=1.7.4->fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading annotated_types-0.8.0-py3-none-any.whl.metadata (15 kB)
Collecting pydantic-core==2.50.1 (from pydantic!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0,>=1.7.4->fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading pydantic_core-2.50.1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (6.5 kB)
Collecting typing-inspection>=0.4.4 (from pydantic!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0,>=1.7.4->fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading typing_inspection-0.4.4-py3-none-any.whl.metadata (2.6 kB)
Collecting anyio<5,>=3.6.2 (from starlette<0.47.0,>=0.40.0->fastapi==0.115.12->-r requirements.txt (line 1))
  Downloading anyio-4.15.1-py3-none-any.whl.metadata (4.7 kB)
Downloading fastapi-0.115.12-py3-none-any.whl (95 kB)
Downloading uvicorn-0.34.2-py3-none-any.whl (62 kB)
Downloading gunicorn-23.0.0-py3-none-any.whl (85 kB)
Downloading google_cloud_firestore-2.21.0-py3-none-any.whl (368 kB)
Downloading google_auth-2.40.3-py2.py3-none-any.whl (216 kB)
Downloading requests-2.32.4-py3-none-any.whl (64 kB)
Downloading cachetools-5.5.2-py3-none-any.whl (10 kB)
Downloading certifi-2026.7.22-py3-none-any.whl (136 kB)
Downloading charset_normalizer-3.5.2-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (257 kB)
Downloading click-8.5.0-py3-none-any.whl (125 kB)
Downloading google_api_core-2.30.3-py3-none-any.whl (173 kB)
Downloading google_cloud_core-2.8.0-py3-none-any.whl (31 kB)
Downloading h11-0.16.0-py3-none-any.whl (37 kB)
Downloading httptools-0.9.0-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (552 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 552.8/552.8 kB 434.4 MB/s eta 0:00:00
Downloading idna-3.20-py3-none-any.whl (69 kB)
Downloading proto_plus-1.29.0-py3-none-any.whl (50 kB)
Downloading protobuf-6.33.6-cp39-abi3-manylinux2014_x86_64.whl (323 kB)
Downloading pyasn1_modules-0.4.2-py3-none-any.whl (181 kB)
Downloading pydantic-2.14.1-py3-none-any.whl (488 kB)
Downloading pydantic_core-2.50.1-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (2.2 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.2/2.2 MB 209.0 MB/s eta 0:00:00
Downloading python_dotenv-1.2.4-py3-none-any.whl (23 kB)
Downloading pyyaml-6.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (807 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 807.9/807.9 kB 462.2 MB/s eta 0:00:00
Downloading rsa-4.9.1-py3-none-any.whl (34 kB)
Downloading starlette-0.46.2-py3-none-any.whl (72 kB)
Downloading typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Downloading urllib3-2.8.0-py3-none-any.whl (135 kB)
Downloading uvloop-0.23.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (4.5 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.5/4.5 MB 245.1 MB/s eta 0:00:00
Downloading watchfiles-1.3.0-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (458 kB)
Downloading websockets-17.2-cp312-cp312-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (225 kB)
Downloading packaging-26.3-py3-none-any.whl (129 kB)
Downloading annotated_types-0.8.0-py3-none-any.whl (13 kB)
Downloading anyio-4.15.1-py3-none-any.whl (132 kB)
Downloading googleapis_common_protos-1.75.5-py3-none-any.whl (307 kB)
Downloading grpcio-1.84.0-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (7.2 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 7.2/7.2 MB 306.4 MB/s eta 0:00:00
Downloading grpcio_status-1.84.0-py3-none-any.whl (14 kB)
Downloading pyasn1-0.6.4-py3-none-any.whl (84 kB)
Downloading typing_inspection-0.4.4-py3-none-any.whl (14 kB)
Installing collected packages: websockets, uvloop, urllib3, typing-extensions, pyyaml, python-dotenv, pyasn1, protobuf, packaging, idna, httptools, h11, click, charset_normalizer, certifi, cachetools, annotated-types, uvicorn, typing-inspection, rsa, requests, pydantic-core, pyasn1-modules, proto-plus, gunicorn, grpcio, googleapis-common-protos, anyio, watchfiles, starlette, pydantic, grpcio-status, google-auth, google-api-core, fastapi, google-cloud-core, google-cloud-firestore
Successfully installed annotated-types-0.8.0 anyio-4.15.1 cachetools-5.5.2 certifi-2026.7.22 charset_normalizer-3.5.2 click-8.5.0 fastapi-0.115.12 google-api-core-2.30.3 google-auth-2.40.3 google-cloud-core-2.8.0 google-cloud-firestore-2.21.0 googleapis-common-protos-1.75.5 grpcio-1.84.0 grpcio-status-1.84.0 gunicorn-23.0.0 h11-0.16.0 httptools-0.9.0 idna-3.20 packaging-26.3 proto-plus-1.29.0 protobuf-6.33.6 pyasn1-0.6.4 pyasn1-modules-0.4.2 pydantic-2.14.1 pydantic-core-2.50.1 python-dotenv-1.2.4 pyyaml-6.0.3 requests-2.32.4 rsa-4.9.1 starlette-0.46.2 typing-extensions-4.16.0 typing-inspection-0.4.4 urllib3-2.8.0 uvicorn-0.34.2 uvloop-0.23.0 watchfiles-1.3.0 websockets-17.2
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.

[notice] A new release of pip is available: 25.0.1 -> 26.2.1
[notice] To update, run: pip install --upgrade pip
Removing intermediate container 20cb1864b703
)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))


Step 4/8 : RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
 Running in 7601d5a29a48
Hit:1 http://deb.debian.org/debian trixie InRelease
Get:2 http://deb.debian.org/debian trixie-updates InRelease [47.3 kB]
Get:3 http://deb.debian.org/debian-security trixie-security InRelease [43.4 kB]
Get:4 http://deb.debian.org/debian trixie/main amd64 Packages [9678 kB]
Get:5 http://deb.debian.org/debian trixie-updates/main amd64 Packages [4412 B]
Get:6 http://deb.debian.org/debian-security trixie-security/main amd64 Packages [267 kB]
Fetched 10.0 MB in 2s (5918 kB/s)
Reading package lists...
Reading package lists...
Building dependency tree...
Reading state information...
The following additional packages will be installed:
  libatomic1 libdrm-amdgpu1 libdrm-common libdrm-intel1 libdrm2 libedit2
  libelf1t64 libexpat1 libgbm1 libgl1-mesa-dri libglvnd0 libglx-mesa0 libglx0
  libllvm19 libpciaccess0 libsensors-config libsensors5 libvulkan1
  libwayland-server0 libx11-6 libx11-data libx11-xcb1 libxau6 libxcb-dri3-0
  libxcb-glx0 libxcb-present0 libxcb-randr0 libxcb-shm0 libxcb-sync1
  libxcb-xfixes0 libxcb1 libxdmcp6 libxext6 libxml2 libxshmfence1 libxxf86vm1
  libz3-4 mesa-libgallium
Suggested packages:
  low-memory-monitor pciutils lm-sensors
Recommended packages:
  libglib2.0-data shared-mime-info xdg-user-dirs mesa-vulkan-drivers
  | vulkan-icd
The following NEW packages will be installed:
  libatomic1 libdrm-amdgpu1 libdrm-common libdrm-intel1 libdrm2 libedit2
  libelf1t64 libexpat1 libgbm1 libgl1 libgl1-mesa-dri libglib2.0-0t64
  libglvnd0 libglx-mesa0 libglx0 libllvm19 libpciaccess0 libsensors-config
  libsensors5 libvulkan1 libwayland-server0 libx11-6 libx11-data libx11-xcb1
  libxau6 libxcb-dri3-0 libxcb-glx0 libxcb-present0 libxcb-randr0 libxcb-shm0
  libxcb-sync1 libxcb-xfixes0 libxcb1 libxdmcp6 libxext6 libxml2 libxshmfence1
  libxxf86vm1 libz3-4 mesa-libgallium
0 upgraded, 40 newly installed, 0 to remove and 1 not upgraded.
Need to get 50.1 MB of archives.
After this operation, 218 MB of additional disk space will be used.
Get:1 http://deb.debian.org/debian trixie/main amd64 libexpat1 amd64 2.8.3-1~deb13u1 [123 kB]
Get:2 http://deb.debian.org/debian trixie/main amd64 libatomic1 amd64 14.2.0-19 [9308 B]
Get:3 http://deb.debian.org/debian trixie/main amd64 libdrm-common all 2.4.124-2 [8288 B]
Get:4 http://deb.debian.org/debian trixie/main amd64 libdrm2 amd64 2.4.124-2 [39.0 kB]
Get:5 http://deb.debian.org/debian trixie/main amd64 libdrm-amdgpu1 amd64 2.4.124-2 [22.6 kB]
Get:6 http://deb.debian.org/debian trixie/main amd64 libpciaccess0 amd64 0.17-3+b3 [51.9 kB]
Get:7 http://deb.debian.org/debian trixie/main amd64 libdrm-intel1 amd64 2.4.124-2 [64.1 kB]
Get:8 http://deb.debian.org/debian trixie/main amd64 libedit2 amd64 3.1-20250104-1 [93.8 kB]
Get:9 http://deb.debian.org/debian trixie/main amd64 libelf1t64 amd64 0.192-4 [189 kB]
Get:10 http://deb.debian.org/debian trixie/main amd64 libwayland-server0 amd64 1.23.1-3 [34.4 kB]
Get:11 http://deb.debian.org/debian trixie/main amd64 libxml2 amd64 2.12.7+dfsg+really2.9.14-2.1+deb13u3 [700 kB]
Get:12 http://deb.debian.org/debian trixie/main amd64 libz3-4 amd64 4.13.3-1 [8560 kB]
Get:13 http://deb.debian.org/debian trixie/main amd64 libllvm19 amd64 1:19.1.7-3+b1 [26.0 MB]
Get:14 http://deb.debian.org/debian trixie/main amd64 libsensors-config all 1:3.6.2-2 [16.2 kB]
Get:15 http://deb.debian.org/debian trixie/main amd64 libsensors5 amd64 1:3.6.2-2 [37.5 kB]
Get:16 http://deb.debian.org/debian trixie/main amd64 libxau6 amd64 1:1.0.11-1 [20.4 kB]
Get:17 http://deb.debian.org/debian trixie/main amd64 libxdmcp6 amd64 1:1.1.5-1 [27.8 kB]
Get:18 http://deb.debian.org/debian trixie/main amd64 libxcb1 amd64 1.17.0-2+b1 [144 kB]
Get:19 http://deb.debian.org/debian trixie/main amd64 libx11-data all 2:1.8.12-1 [343 kB]
Get:20 http://deb.debian.org/debian trixie/main amd64 libx11-6 amd64 2:1.8.12-1 [815 kB]
Get:21 http://deb.debian.org/debian trixie/main amd64 libx11-xcb1 amd64 2:1.8.12-1 [247 kB]
Get:22 http://deb.debian.org/debian trixie/main amd64 libxcb-dri3-0 amd64 1.17.0-2+b1 [107 kB]
Get:23 http://deb.debian.org/debian trixie/main amd64 libxcb-present0 amd64 1.17.0-2+b1 [106 kB]
Get:24 http://deb.debian.org/debian trixie/main amd64 libxcb-randr0 amd64 1.17.0-2+b1 [117 kB]
Get:25 http://deb.debian.org/debian trixie/main amd64 libxcb-sync1 amd64 1.17.0-2+b1 [109 kB]
Get:26 http://deb.debian.org/debian trixie/main amd64 libxcb-xfixes0 amd64 1.17.0-2+b1 [109 kB]
Get:27 http://deb.debian.org/debian trixie/main amd64 libxshmfence1 amd64 1.3.3-1 [10.9 kB]
Get:28 http://deb.debian.org/debian trixie/main amd64 mesa-libgallium amd64 25.0.7-2+deb13u1 [9630 kB]
Get:29 http://deb.debian.org/debian trixie/main amd64 libgbm1 amd64 25.0.7-2+deb13u1 [44.6 kB]
Get:30 http://deb.debian.org/debian trixie/main amd64 libglvnd0 amd64 1.7.0-1+b2 [52.0 kB]
Get:31 http://deb.debian.org/debian trixie/main amd64 libxcb-glx0 amd64 1.17.0-2+b1 [122 kB]
Get:32 http://deb.debian.org/debian trixie/main amd64 libxcb-shm0 amd64 1.17.0-2+b1 [105 kB]
Get:33 http://deb.debian.org/debian trixie/main amd64 libxext6 amd64 2:1.3.4-1+b3 [50.4 kB]
Get:34 http://deb.debian.org/debian trixie/main amd64 libxxf86vm1 amd64 1:1.1.4-1+b4 [19.3 kB]
Get:35 http://deb.debian.org/debian trixie/main amd64 libvulkan1 amd64 1.4.309.0-1 [130 kB]
Get:36 http://deb.debian.org/debian trixie/main amd64 libgl1-mesa-dri amd64 25.0.7-2+deb13u1 [46.2 kB]
Get:37 http://deb.debian.org/debian trixie/main amd64 libglx-mesa0 amd64 25.0.7-2+deb13u1 [143 kB]
Get:38 http://deb.debian.org/debian trixie/main amd64 libglx0 amd64 1.7.0-1+b2 [34.9 kB]
Get:39 http://deb.debian.org/debian trixie/main amd64 libgl1 amd64 1.7.0-1+b2 [89.5 kB]
Get:40 http://deb.debian.org/debian trixie/main amd64 libglib2.0-0t64 amd64 2.84.4-3~deb13u5 [1521 kB]
debconf: unable to initialize frontend: Dialog
debconf: (TERM is not set, so the dialog frontend is not usable.)
debconf: falling back to frontend: Readline
debconf: unable to initialize frontend: Readline
debconf: (Can't locate Term/ReadLine.pm in @INC (you may need to install the Term::ReadLine module) (@INC entries checked: /etc/perl /usr/local/lib/x86_64-linux-gnu/perl/5.40.1 /usr/local/share/perl/5.40.1 /usr/lib/x86_64-linux-gnu/perl5/5.40 /usr/share/perl5 /usr/lib/x86_64-linux-gnu/perl-base /usr/lib/x86_64-linux-gnu/perl/5.40 /usr/share/perl/5.40 /usr/local/lib/site_perl) at /usr/share/perl5/Debconf/FrontEnd/Readline.pm line 8, <STDIN> line 40.)
debconf: falling back to frontend: Teletype
debconf: unable to initialize frontend: Teletype
debconf: (This frontend requires a controlling tty.)
debconf: falling back to frontend: Noninteractive
Fetched 50.1 MB in 1s (84.4 MB/s)


)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))



Installing collected packages: urllib3, typing-extensions, PyMuPDF, pycparser, pyasn1, protobuf, numpy, idna, google-crc32c, charset_normalizer, certifi, requests, pyasn1-modules, proto-plus, opentelemetry-api, opencv-python-headless, grpcio, googleapis-common-protos, google-resumable-media, cffi, grpcio-status, cryptography, google-auth, google-api-core, google-cloud-core, google-cloud-storage, google-cloud-firestore, google-cloud-documentai
Successfully installed PyMuPDF-1.26.1 certifi-2026.7.22 cffi-2.1.1 charset_normalizer-3.5.2 cryptography-50.0.2 google-api-core-2.42.0 google-auth-2.62.0 google-cloud-core-2.8.0 google-cloud-documentai-3.6.0 google-cloud-firestore-2.21.0 google-cloud-storage-3.1.1 google-crc32c-1.9.0 google-resumable-media-2.11.0 googleapis-common-protos-1.75.5 grpcio-1.84.0 grpcio-status-1.84.0 idna-3.20 numpy-2.2.6 opencv-python-headless-4.11.0.86 opentelemetry-api-1.45.1 proto-plus-1.29.0 protobuf-6.33.6 pyasn1-0.6.4 pyasn1-modules-0.4.2 pycparser-3.11 requests-2.34.2 typing-extensions-4.16.0 urllib3-2.8.0
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager, possibly rendering your system unusable. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv. Use the --root-user-action option if you know what you are doing and want to suppress this warning.

[notice] A new release of pip is available: 25.0.1 -> 26.2.1
[notice] To update, run: pip install --upgrade pip
Removing intermediate container fda74b1fe636

)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))


== API ==
ERROR: (gcloud.run.deploy) argument --set-env-vars: Bad syntax for dict arg: [grafemapdf.iam.gserviceaccount.com]. Please see `gcloud topic flags-file` or `gcloud topic escaping` for information on providing list or dictionary flag values with special characters.
Usage: gcloud run deploy [[SERVICE] --namespace=NAMESPACE] [optional flags]
  optional flags may be  --add-cloudsql-instances | --add-custom-audiences |
                         --add-volume | --add-volume-mount |
                         --allow-unauthenticated | --args | --async |
                         --automatic-updates | --base-image |
                         --binary-authorization | --breakglass |
                         --build-env-vars-file | --build-service-account |
                         --build-worker-pool | --clear-base-image |
                         --clear-binary-authorization | --clear-build-env-vars |
                         --clear-build-service-account |
                         --clear-build-worker-pool |
                         --clear-cloudsql-instances | --clear-custom-audiences |
                         --clear-encryption-key-shutdown-hours |
                         --clear-env-vars | --clear-key | --clear-labels |
                         --clear-network | --clear-network-tags |
                         --clear-post-key-revocation-action-type |
                         --clear-secrets | --clear-volume-mounts |
                         --clear-volumes | --clear-vpc-connector | --command |
                         --concurrency | --container | --cpu | --cpu-boost |
                         --cpu-throttling | --default-url | --depends-on |
                         --deploy-health-check | --description |
                         --encryption-key-shutdown-hours | --env-vars-file |
                         --execution-environment | --function | --gpu |
                         --gpu-type | --gpu-zonal-redundancy | --help | --iap |
                         --image | --ingress | --invoker-iam-check | --key |
                         --labels | --liveness-probe | --max | --max-instances |
                         --memory | --min | --min-instances | --namespace |
                         --network | --network-tags | --port |
                         --post-key-revocation-action-type | --readiness-probe |
                         --region | --regions | --remove-build-env-vars |
                         --remove-cloudsql-instances | --remove-containers |
                         --remove-custom-audiences | --remove-env-vars |
                         --remove-labels | --remove-secrets | --remove-volume |
                         --remove-volume-mount | --revision-suffix | --scaling |
                         --scaling-concurrency-target | --scaling-cpu-target |
                         --service-account | --session-affinity |
                         --set-build-env-vars | --set-cloudsql-instances |
                         --set-custom-audiences | --set-env-vars |
                         --set-secrets | --source | --startup-probe | --subnet |
                         --tag | --timeout | --no-traffic |
                         --update-build-env-vars | --update-env-vars |
                         --update-labels | --update-secrets | --use-http2 |
                         --vpc-connector | --vpc-egress | --workdir

For detailed information on this command and its flags, run:
  gcloud run deploy --help
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ ^C

)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))

atest: digest: sha256:3fd768a8d2912833e67bc2209a1a889f449c5b80b852e6209437c31c5cd89027 size: 2206
DONE
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
ID: b93d55f3-ee47-4ef5-aa1a-c0ff30dd44ce
CREATE_TIME: 2026-10-14T21:38:00+00:00
DURATION: 5M3S
SOURCE: gs://grafemapdf_cloudbuild/source/1792013879.725388-15cac0be25ce4b9fa6b2d2a27afdd688.tgz
IMAGES: us-central1-docker.pkg.dev/grafemapdf/cognotxt/worker (+1 more)
STATUS: SUCCESS

== Cloud Run Job worker ==
ERROR: (gcloud.run.jobs.create) You do not currently have an active account selected.
Please run:

  $ gcloud auth login

to obtain new credentials.

If you have already logged in with a different account, run:

  $ gcloud config set account ACCOUNT

to select an already authenticated account to use.
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ pip install --upgrade pip
Defaulting to user installation because normal site-packages is not writeable
Requirement already satisfied: pip in /usr/lib/python3/dist-packages (24.0)
Collecting pip
  Downloading pip-26.2.1-py3-none-any.whl.metadata (4.6 kB)
Downloading pip-26.2.1-py3-none-any.whl (1.8 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.8/1.8 MB 16.8 MB/s eta 0:00:00
Installing collected packages: pip
  WARNING: The scripts pip, pip3 and pip3.12 are installed in '/home/arquitetura_joel/.local/bin' which is not on PATH.
  Consider adding this directory to PATH or, if you prefer to suppress this warning, use --no-warn-script-location.
Successfully installed pip-26.2.1
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ export PATH="$PATH:/home/arquitetura_joel/.local/bin"
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 

)))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))

O build terminou corretamente. O erro agora é só porque o gcloud ficou sem uma conta ativa selecionada.
O comando:
export PATH="$PATH:/home/arquitetura_joel/.local/bin"

não corrige isso; ele só ajusta o pip.
Execute nesta ordem:
gcloud auth list

Se aparecer sua conta, por exemplo:
ACCOUNT
arquitetura.joel@gmail.com

mas sem * na coluna ACTIVE, selecione-a:
gcloud config set account arquitetura.joel@gmail.com

Depois confirme o projeto:
gcloud config set project grafemapdf

E valide:
gcloud config list

Você deve ver algo parecido com:
[core]
account = arquitetura.joel@gmail.com
project = grafemapdf

O Google confirma que gcloud auth list mostra as contas armazenadas e que gcloud config set account ... seleciona o principal ativo. Google Cloud Documentation
Se gcloud auth list não mostrar nenhuma conta, então faça:
gcloud auth login

e depois:
gcloud config set account arquitetura.joel@gmail.com
gcloud config set project grafemapdf

Antes de rodar tudo novamente
Teste primeiro se sua autenticação realmente voltou:
gcloud run jobs list \
  --region us-central1 \
  --project grafemapdf

Se listar os jobs ou simplesmente retornar uma lista vazia sem erro de autenticação, está resolvido.
Depois você pode continuar com:
./infra/deploy.sh

Como as imagens Docker já foram construídas com SUCCESS, o script pode refazer alguns passos, mas isso não é problema.
Se quiser evitar repetir os builds, você também pode executar manualmente apenas a parte do script a partir de:
== Cloud Run Job worker ==

O erro atual não é mais de IAM nem de dependências Python. É somente a seleção da conta ativa no gcloud.

((((((((((((((((((((((((((((((((((((((((((((  CORREÇÃO  ((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((((()))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))))


arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud auth list
Credentialed Accounts

ACTIVE: 
ACCOUNT: arquitetura.joel@gmail.com

To set the active account, run:
    $ gcloud config set account `ACCOUNT`

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud config set account arquitetura.joel@gmail.com
Updated property [core/account].
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud auth list
Credentialed Accounts

ACTIVE: *
ACCOUNT: arquitetura.joel@gmail.com

To set the active account, run:
    $ gcloud config set account `ACCOUNT`

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud config set account arquitetura.joel@gmail.com
Updated property [core/account].
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud config set project grafemapdf
Updated property [core/project].
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 



arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ gcloud run jobs list \
  --region us-central1 \
  --project grafemapdf
✔
JOB: cognotxt-worker
REGION: us-central1
LAST RUN AT: 
CREATED: 2026-10-14 20:52:28 UTC
CREATED BY: arquitetura.joel@gmail.com
arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ 





======================================================================================================================================================

arquitetura_joel@cloudshell:~/cognotxt_gcp (grafemapdf)$ ./infra/deploy.sh

======================================================================================================================================================
































































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
