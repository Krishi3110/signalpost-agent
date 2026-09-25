import asyncio
import argparse
import json
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials, fetch_brreg_roles
from scraper import scrape_company_website

async def process_company(orgnr: str, output_file: str):
    profile = await fetch_brreg_basic_info(orgnr)
    if not profile:
        return
    
    profile = await fetch_brreg_financials(profile)
    profile = await fetch_brreg_roles(profile)
    profile = await scrape_company_website(profile) 
    
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(profile.model_dump_json() + "\n")

async def main():
    parser = argparse.ArgumentParser(description="Signalpost Agent")
    parser.add_argument("--input", required=True, help="Input JSON file with org numbers")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            org_numbers = json.load(f)
    except Exception as e:
        print(f"Failed to read input file: {e}")
        return

    open(args.output, "w", encoding="utf-8").close()
    semaphore = asyncio.Semaphore(5)
    
    async def sem_process(orgnr):
        async with semaphore:
            await process_company(str(orgnr), args.output)
            
    tasks = [sem_process(orgnr) for orgnr in org_numbers]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
