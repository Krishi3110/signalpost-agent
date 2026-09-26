import asyncio
import argparse
import json
import sys
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials, fetch_brreg_roles
from scraper import scrape_company_website
from models import ResultEnvelope, ResultState

async def process_company(orgnr: str) -> ResultEnvelope:
    try:
        print(f"Processing {orgnr}...", file=sys.stderr)
        profile = await fetch_brreg_basic_info(orgnr)
        if not profile:
            return ResultEnvelope(orgnr=orgnr, state=ResultState.NOT_AVAILABLE, error_details="Not found in BRREG basic info")
        
        profile = await fetch_brreg_financials(profile)
        profile = await fetch_brreg_roles(profile)
        profile = await scrape_company_website(profile) 
        
        return ResultEnvelope(orgnr=orgnr, state=ResultState.AVAILABLE, profile=profile)
        
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        err_str = str(e).lower()
        blocked_keywords = ["403", "429", "access denied", "forbidden", "cloudflare", "captcha", "robot check"]
        if any(kw in err_str for kw in blocked_keywords):
            return ResultEnvelope(orgnr=orgnr, state=ResultState.BLOCKED, error_details=f"Blocked: {str(e)}")
        return ResultEnvelope(orgnr=orgnr, state=ResultState.FAILED, error_details=f"Unexpected execution failure: {str(e)}")

async def main():
    parser = argparse.ArgumentParser(description="Signalpost Agent")
    parser.add_argument("--input", required=True, help="Input JSON file with org numbers")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            org_numbers = json.load(f)
    except Exception as e:
        print(f"Failed to read input file: {e}", file=sys.stderr)
        return

    semaphore = asyncio.Semaphore(5)
    
    async def sem_process(orgnr):
        async with semaphore:
            return await process_company(str(orgnr))
            
    tasks = [sem_process(orgnr) for orgnr in org_numbers]
    results = await asyncio.gather(*tasks)
    
    # Strictly output sequentially to guarantee 100 lines and prevent output corruption
    with open(args.output, "w", encoding="utf-8") as f:
        for envelope in results:
            json_line = envelope.model_dump_json()
            print(json_line, file=sys.stdout)
            f.write(json_line + "\n")
            
    print("Batch complete.", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
