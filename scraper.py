import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import json
import os
import asyncio
from datetime import datetime, timezone
from models import Fact, CompanyProfile

# Initialize the new SDK client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def scrape_company_website(profile: CompanyProfile) -> CompanyProfile:
    """Scrapes the official website and extracts unstructured facts via Gemini."""
    
    if "website" not in profile.facts:
        return profile
        
    url = profile.facts["website"].value
    
    # Increased timeout and added headers to bypass basic bot protection
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
        try:
            response = await http_client.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed to fetch website. HTTP Status: {response.status_code}")
                return profile
            
            # Clean HTML
            soup = BeautifulSoup(response.text, "html.parser")
            for element in soup(["script", "style", "footer", "nav", "header"]):
                element.decompose()
                
            text = soup.get_text(separator=' ', strip=True)[:3000]
            
            prompt = f"""
            Analyze the following text from a Norwegian company's website. 
            Extract the following information:
            1. mission_statement (a brief string summarizing their goal/business, or null)
            2. executive_team (a string listing key executives/CEO, or null)
            
            Respond ONLY in strict JSON format. Do NOT invent or guess information.
            
            Text:
            {text}
            """
            
            # 4. LLM Extraction with Retry Logic
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = await client.aio.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        ),
                    )
                    
                    result = json.loads(response.text)
                    timestamp = datetime.now(timezone.utc)
                    
                    def create_fact(value) -> Fact:
                        return Fact(value=value, source_url=url, fetched_at=timestamp)
                    
                    if result.get("mission_statement"):
                        profile.facts["mission_statement"] = create_fact(result["mission_statement"])
                        
                    if result.get("executive_team"):
                        profile.facts["executive_team"] = create_fact(result["executive_team"])
                        
                    break  # Success! Break out of the retry loop
                    
                except Exception as e:
                    if "503" in str(e) and attempt < max_retries - 1:
                        wait_time = 2 ** attempt  # Wait 1s, then 2s...
                        print(f"API busy (503). Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"Scraping/LLM Error: {repr(e)}")
                        break
                        
        except Exception as e:
            # TEMPORARILY PRINT THE ERROR FOR DEBUGGING
            print(f"Scraping/LLM Error: {repr(e)}")
            
    return profile
