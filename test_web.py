import asyncio
import json
from api_gov import fetch_brreg_basic_info
from scraper import scrape_company_website

async def main():
    orgnr = None
    try:
        with open('submission_profiles.jsonl', 'r', encoding='utf-8') as f:
            for line in f:
                r = json.loads(line)
                if 'website' in r.get('facts', {}):
                    orgnr = r['orgnr']
                    break
    except Exception:
        pass
        
    if not orgnr:
        orgnr = "923609016" # Equinor fallback

    print(f"Testing orgnr: {orgnr}")
    profile = await fetch_brreg_basic_info(orgnr)
    if not profile:
        print("BRREG lookup failed")
        return
    print("Website:", profile.facts.get("website"))
    
    # Enable debug logging in scraper by overriding it or we can just see what happens
    profile = await scrape_company_website(profile)
    print("\nFINAL FACTS:")
    for key, fact in profile.facts.items():
        print(key, "=>", fact.value)

asyncio.run(main())
