import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import json
import os
import asyncio
from datetime import datetime, timezone
from models import Fact, CompanyProfile

# Define the exact extraction schema for the LLM
class Executive(BaseModel):
    name: str
    title: str

class WebsiteExtraction(BaseModel):
    mission_statement: str | None = None
    executive_team: list[Executive] = Field(default_factory=list)
    contact_emails: list[str] = Field(default_factory=list)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def scrape_company_website(profile: CompanyProfile) -> CompanyProfile:
    """Scrapes the official website and extracts unstructured facts via Gemini."""
    if "website" not in profile.facts:
        return profile
        
    url = profile.facts["website"].value
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
        try:
            response = await http_client.get(url, headers=headers)
            if response.status_code != 200:
                return profile
            
            soup = BeautifulSoup(response.text, "html.parser")
            for element in soup(["script", "style", "footer", "nav", "header"]):
                element.decompose()
                
            text = soup.get_text(separator=' ', strip=True)[:3000]
            
            prompt = f"""
            Analyze the following text from a Norwegian company's website. 
            Extract the mission statement, executive team, and contact emails.
            Do NOT invent or guess information.
            Text:
            {text}
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    res = await client.aio.models.generate_content(
                        model='gemini-3.8-flash',
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=WebsiteExtraction, # Enforces strict schema
                            temperature=0.0,
                        ),
                    )
                    
                    # Safely parse the guaranteed JSON response back into our Pydantic model
                    result = WebsiteExtraction.model_validate_json(res.text)
                    timestamp = datetime.now(timezone.utc)
                    
                    def create_fact(value) -> Fact:
                        return Fact(value=value, source_url=url, fetched_at=timestamp)
                    
                    if result.mission_statement:
                        profile.facts["mission_statement"] = create_fact(result.mission_statement)
                        
                    if result.executive_team:
                        team_str = ", ".join([f"{ex.name} ({ex.title})" for ex in result.executive_team])
                        profile.facts["executive_team"] = create_fact(team_str)
                        
                    if result.contact_emails:
                        profile.facts["contact_emails"] = create_fact(", ".join(result.contact_emails))
                        
                    break 
                    
                except Exception as e:
                    if "503" in str(e) or "429" in str(e):
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)
                        else:
                            break
                    else:
                        break
                        
        except Exception:
            pass
            
    return profile
