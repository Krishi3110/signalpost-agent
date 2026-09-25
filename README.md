# SignalPost Agent

## Architecture
BRREG → Financials → Roles → Website → Gemini → Pydantic

## Setup
Ensure Python 3.11+ is installed, then install the dependencies:
```bash
pip install -r requirements.txt
```

## Run
```bash
docker build -t signalpost-agent .
docker run --rm -v "$(pwd)/test_input.json:/app/test_input.json" --env GEMINI_API_KEY="your_key" signalpost-agent --input /app/test_input.json --output /app/results.jsonl
```

## Input
A JSON array of 9-digit Norwegian organization numbers.

## Output
A JSONL file containing complete, deterministic, and LLM-augmented company profiles conforming strictly to Pydantic schemas.

## Data sources
BRREG (Enhetsregisteret, Regnskapsregisteret, and Roller APIs) + official company websites.
