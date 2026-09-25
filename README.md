# Signalpost Data Extraction Agent

An autonomous agent designed to extract determinist Norwegian corporate records from Brønnøysundregistrene (Enhetsregisteret and Regnskapsregisteret), augmented with unstructured facts extracted from official company websites via Gemini 3.8 Flash.

## Execution
The agent accepts a JSON array of organization numbers and outputs structured Pydantic profiles to a JSONL file.

```bash
docker build -t signalpost-agent .
docker run --rm -v "$(pwd)/test_input.json:/app/test_input.json" --env GEMINI_API_KEY="your_key" signalpost-agent --input /app/test_input.json --output /app/results.jsonl
```
