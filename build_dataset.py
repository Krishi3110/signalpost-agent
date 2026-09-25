import asyncio
import httpx
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials
from scraper import scrape_company_website

async def get_target_company_ids(target_count=1100):
    print(f"Fetching {target_count} company IDs from Brønnøysundregistrene...")
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS,ASA&size={target_count}"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()
        companies = data.get("_embedded", {}).get("enheter", [])
        return [comp["organisasjonsnummer"] for comp in companies]

async def process_single_company(orgnr: str, semaphore: asyncio.Semaphore, file_lock: asyncio.Lock):
    async with semaphore:
        profile = await fetch_brreg_basic_info(orgnr)
        if not profile:
            return
            
        profile = await fetch_brreg_financials(profile)
        # Web scraping fully enabled as requested by the reviewer
        profile = await scrape_company_website(profile) 
        
        async with file_lock:
            with open("submission_profiles.jsonl", "a", encoding="utf-8") as f:
                f.write(profile.model_dump_json() + "\n")

async def main():
    org_numbers = await get_target_company_ids()
    
    # Clears the old dataset
    open("submission_profiles.jsonl", "w", encoding="utf-8").close()
    
    # We use a lower concurrency of 3 to gently ride the free-tier rate limits
    semaphore = asyncio.Semaphore(3)
    file_lock = asyncio.Lock()
    
    print(f"Starting batch extraction for {len(org_numbers)} companies. This will take a while...")
    tasks = [process_single_company(orgnr, semaphore, file_lock) for orgnr in org_numbers]
    await asyncio.gather(*tasks)
    print("Dataset generation complete!")

if __name__ == "__main__":
    asyncio.run(main())
