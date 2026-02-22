# RockAuto API

FastAPI service for searching RockAuto parts catalog.

## Endpoints

- `GET /` - Status check
- `GET /health` - Health check
- `POST /parts` - Search parts by make, year, model, category

## Deployment

Deployed on Railway: https://rockauto-api-production.up.railway.app

## Usage

```bash
curl -X POST "https://rockauto-api-production.up.railway.app/parts?make=Honda&year=2015&model=Civic&category=body"
```
