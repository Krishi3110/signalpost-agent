import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import os
import asyncio
from datetime import datetime, timezone
from models import Fact, CompanyProfile

class Executive(BaseModel):
    name: str
    title: str

class WebsiteFacts(BaseModel):
    mission_statement: str | None = None
    executive_team: list[Executive] = Field(default_factory=list)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def scrape_company_website(profile: CompanyProfile) -> CompanyProfile:
    if "website" not in profile.facts:
        return profile
        
    url = profile.facts["website"].value
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
        try:
            response = await http_client.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Website fetch failed for {profile.orgnr}: {response.status_code}")
                return profile
            
            soup = BeautifulSoup(response.text, "html.parser")
            for element in soup(["script", "style", "footer", "nav", "header"]):
                element.decompose()
                
            text = soup.get_text(separator=' ', strip=True)[:3000]
            
            prompt = f"Extract the mission statement and executive team from this Norwegian company website text. Do NOT invent information.\nText: {text}"
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    res = await client.aio.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=WebsiteFacts,
                            temperature=0.0,
                        ),
                    )
                    
                    result = WebsiteFacts.model_validate_json(res.text)
                    timestamp = datetime.now(timezone.utc)
                    
                    def create_fact(value) -> Fact:
                        return Fact(value=value, source_url=url, fetched_at=timestamp)
                    
                    if result.mission_statement:
                        profile.facts["mission_statement"] = create_fact(result.mission_statement)
                        
                    if result.executive_team:
                        team_str = ", ".join([f"{ex.name} ({ex.title})" for ex in result.executive_team])
                        profile.facts["executive_team"] = create_fact(team_str)
                        
                    break 
                    
                except Exception as e:
                    if "503" in str(e) or "429" in str(e):
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                        else:
                            print(f"LLM Rate limit exhausted for {profile.orgnr}")
                            break
                    else:
                        print(f"LLM extraction error for {profile.orgnr}: {repr(e)}")
                        break
                        
        except Exception as e:
            print(f"Website scraping error for {profile.orgnr}: {repr(e)}")
            
    return profile
