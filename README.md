# SignalPost Agent

## Architecture
BRREG → Financials → Roles → Website → Gemini 3.8 Flash → `ResultEnvelope`

## Setup (Local)
Ensure Python 3.11+ is installed, then install the dependencies and headless browser required for the 3-tier scraper:
```bash
pip install -r requirements.txt
playwright install --with-deps chromium
```

## Running the Evaluator Contract
The agent requires a JSON array of 9-digit Norwegian organization numbers. It emits exactly one JSON `ResultEnvelope` per input company to `stdout`.

```bash
export GEMINI_API_KEY="your_api_key"
python main.py --input test_input.json --output results.jsonl > stdout.txt
```

*(Note: All pipeline logs and errors are cleanly diverted to `sys.stderr`, preserving a pristine `ResultEnvelope` JSONL stream on `stdout`.)*

## Docker Deployment
```bash
docker build -t signalpost-agent .
docker run --rm -i \
  -e GEMINI_API_KEY="your_api_key" \
  -v "$(pwd)/test_input.json:/app/test_input.json" \
  -v "$(pwd)/results.jsonl:/app/results.jsonl" \
  signalpost-agent --input /app/test_input.json --output /app/results.jsonl
```

## Output States
The `ResultEnvelope` strictly adheres to one of six evaluator states: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, or `failed`.

## Data sources
BRREG (Enhetsregisteret, Regnskapsregisteret, and Roller APIs) + official company websites.
