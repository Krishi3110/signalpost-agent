import asyncio
from api_gov import fetch_brreg_basic_info, fetch_brreg_financials
from scraper import scrape_company_website

async def main():
    orgnr = "923609016" # Equinor
    
    profile = await fetch_brreg_basic_info(orgnr)
    if profile:
        profile = await fetch_brreg_financials(profile)
        # 3. Append unstructured web data
        profile = await scrape_company_website(profile)
        
        print(profile.model_dump_json(indent=2))
    else:
        print("Failed to fetch company.")

if __name__ == "__main__":
    asyncio.run(main())
