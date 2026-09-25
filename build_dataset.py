import asyncio
import httpx
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials, fetch_brreg_roles
from scraper import scrape_company_website

TARGET_COUNT = 1100

async def get_target_company_ids():
    print(f"Fetching {TARGET_COUNT} company IDs from Brønnøysundregistrene...")
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS,ASA&size={TARGET_COUNT}"
    
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
        profile = await fetch_brreg_roles(profile)
        profile = await scrape_company_website(profile) 
        
        async with file_lock:
            with open("submission_profiles.jsonl", "a", encoding="utf-8") as f:
                f.write(profile.model_dump_json() + "\n")

async def main():
    org_numbers = await get_target_company_ids()
    open("submission_profiles.jsonl", "w", encoding="utf-8").close()
    
    # Process one by one to ensure absolute stability and prevent dropped connections
    semaphore = asyncio.Semaphore(1)
    file_lock = asyncio.Lock()
    
    print(f"Starting batch extraction. This will take several hours to respect rate limits.")
    tasks = [process_single_company(orgnr, semaphore, file_lock) for orgnr in org_numbers]
    await asyncio.gather(*tasks)
    print("Dataset generation complete!")

if __name__ == "__main__":
    asyncio.run(main())
