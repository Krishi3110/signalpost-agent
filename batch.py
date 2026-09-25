import asyncio
import httpx
import json
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials
from scraper import scrape_company_website

async def get_1000_company_ids():
    """Fetches 1000 AS/ASA company IDs from the Norwegian registry."""
    print("Fetching 1,000 company IDs...")
    # Requesting 1000 companies, filtering for AS and ASA
    url = "https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS,ASA&size=1000"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()
        
        # Extract the orgnr from the embedded items
        companies = data.get("_embedded", {}).get("enheter", [])
        org_numbers = [comp["organisasjonsnummer"] for comp in companies]
        
        print(f"Successfully fetched {len(org_numbers)} IDs.")
        return org_numbers

async def process_single_company(orgnr: str, semaphore: asyncio.Semaphore, file_lock: asyncio.Lock):
    """Runs the full pipeline for a single company under concurrency limits."""
    async with semaphore:
        profile = await fetch_brreg_basic_info(orgnr)
        if not profile:
            return
            
        profile = await fetch_brreg_financials(profile)
        
        # TEMPORARILY DISABLED to bypass free-tier rate limits for the batch run
        # profile = await scrape_company_website(profile) 
        
        # Write to file safely using a lock
        async with file_lock:
            with open("submission_profiles.jsonl", "a", encoding="utf-8") as f:
                f.write(profile.model_dump_json() + "\n")

async def main():
    # 1. Get the IDs
    org_numbers = await get_1000_company_ids()
    
    # 2. Setup concurrency controls
    # Limit to 10 simultaneous pipelines so we don't overwhelm the APIs
    semaphore = asyncio.Semaphore(10)
    file_lock = asyncio.Lock()
    
    # Clear the output file if it exists
    open("submission_profiles.jsonl", "w", encoding="utf-8").close()
    
    print("Starting batch processing. This may take a few minutes...")
    
    # 3. Create and run all tasks concurrently
    tasks = [
        process_single_company(orgnr, semaphore, file_lock) 
        for orgnr in org_numbers
    ]
    
    # Gather will run them all, respecting the semaphore limit
    await asyncio.gather(*tasks)
    
    print("Batch complete! Check submission_profiles.jsonl")

if __name__ == "__main__":
    asyncio.run(main())
