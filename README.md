# MedFlow AI - Phase 1

A local full-stack foundation for an AI-assisted medical document processing workflow.

## Architecture

React + TypeScript -> FastAPI -> PostgreSQL -> local document storage

The current background processor is mocked. In later phases it will become:

S3 -> SQS -> Processing Lambda -> Textract -> LLM -> PostgreSQL

## Start PostgreSQL

```bash
docker compose up -d
```

## Start the backend

```bash
cd backend
python -m venv .venv
```

Windows Command Prompt:

```bat
.venv\Scripts\activate
copy .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Backend:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Start the frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend:
- http://localhost:5173

## Current API endpoints

- `POST /api/v1/documents`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{document_id}`

## Phase 2

- Connect the React UI to these APIs
- Replace mocked processing with real OCR
- Add PostgreSQL migrations with Alembic
- Add tests

Use synthetic documents only.
