import httpx
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import os
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from models import Fact, CompanyProfile

class FactExtraction(BaseModel):
    value: str
    source_url: str

class WebsiteFacts(BaseModel):
    mission_statement: FactExtraction | None = None
    company_description: FactExtraction | None = None

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def fetch_page(http_client, url, headers):
    try:
        response = await http_client.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            return soup
    except Exception:
        pass
    return None

def clean_soup_text(soup):
    for element in soup(["script", "style", "footer", "nav", "header"]):
        element.decompose()
    return soup.get_text(separator=' ', strip=True)

async def scrape_company_website(profile: CompanyProfile) -> CompanyProfile:
    if "website" not in profile.facts:
        return profile
        
    url = profile.facts["website"].value
    base_domain = urlparse(url).netloc.lower()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
        try:
            soup = await fetch_page(http_client, url, headers)
            if not soup:
                print(f"Website fetch failed for {profile.orgnr}")
                return profile
            
            keywords = ['about', 'team', 'leadership', 'om', 'ledelse', 'kontakt', 'about-us']
            links_to_fetch = []
            
            # Discover links BEFORE cleaning the soup, since nav links are highly relevant
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text().lower()
                if any(k in href.lower() or k in text for k in keywords):
                    full_url = urljoin(url, href)
                    if full_url.startswith('http'):
                        candidate_domain = urlparse(full_url).netloc.lower()
                        # Enforce same-domain to avoid scraping LinkedIn/Facebook "about" links
                        if candidate_domain == base_domain and full_url not in links_to_fetch and full_url != url:
                            links_to_fetch.append(full_url)
                            if len(links_to_fetch) >= 2:
                                break
            
            # Now we clean the text for the LLM
            texts = [f"--- URL: {url} ---\n{clean_soup_text(soup)}"]
                            
            for l in links_to_fetch:
                sub_soup = await fetch_page(http_client, l, headers)
                if sub_soup:
                    texts.append(f"--- URL: {l} ---\n{clean_soup_text(sub_soup)}")
                    
            combined_text = "\n\n".join(texts)[:8000]
            
            allowed_urls = {url} | set(links_to_fetch)
            
            prompt = f"""
            You are analyzing text extracted from various pages of a Norwegian company's website.
            Each section begins with "--- URL: <url> ---".
            
            Extract the company's mission statement and a general company description.
            For each fact you extract, you MUST provide the exact `source_url` from the section where you found the information.
            
            Do NOT invent information. If it is not present, leave it null.
            
            Text: 
            {combined_text}
            """
            
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
                    
                    # Validate that the LLM didn't hallucinate a URL
                    if result.mission_statement and result.mission_statement.value:
                        src_url = result.mission_statement.source_url
                        if src_url in allowed_urls:
                            profile.facts["mission_statement"] = Fact(
                                value=result.mission_statement.value,
                                source_url=src_url,
                                fetched_at=timestamp
                            )
                        
                    if result.company_description and result.company_description.value:
                        src_url = result.company_description.source_url
                        if src_url in allowed_urls:
                            profile.facts["company_description"] = Fact(
                                value=result.company_description.value,
                                source_url=src_url,
                                fetched_at=timestamp
                            )
                        
                    break 
                    
                except Exception as e:
                    if "503" in str(e) or "429" in str(e) or "quota" in str(e).lower():
                        if attempt < max_retries - 1:
                            wait_time = 30 * (attempt + 1) 
                            print(f"Rate limited on {profile.orgnr}. Waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                        else:
                            print(f"LLM Rate limit exhausted for {profile.orgnr}")
                            break
                    else:
                        print(f"LLM extraction error for {profile.orgnr}: {repr(e)}")
                        break
                        
        except Exception as e:
            print(f"Website scraping error for {profile.orgnr}: {repr(e)}")
            
    return profile
