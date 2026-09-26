import httpx
import re
import sys
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import os
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
from models import Fact, CompanyProfile
import ollama

LLM_BACKEND = os.getenv("LLM_BACKEND", "gemini") # Options: "ollama" or "gemini"
OLLAMA_MODEL = "qwen3:14b"

class FactExtraction(BaseModel):
    value: str
    source_url: str

class WebsiteFacts(BaseModel):
    mission_statement: FactExtraction | None = None
    company_description: FactExtraction | None = None

client = None
if LLM_BACKEND == "gemini":
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

def extract_metadata(soup):
    meta_text = []
    if soup.title and soup.title.string:
        meta_text.append(f"Title: {soup.title.string.strip()}")
    desc = soup.find('meta', attrs={'name': 'description'})
    if desc and desc.get('content'):
        meta_text.append(f"Meta Description: {desc['content'].strip()}")
    og_desc = soup.find('meta', attrs={'property': 'og:description'})
    if og_desc and og_desc.get('content'):
        meta_text.append(f"OG Description: {og_desc['content'].strip()}")
    return "\n".join(meta_text)

def clean_soup_text(soup):
    meta_text = extract_metadata(soup)
    s = BeautifulSoup(str(soup), "html.parser")
    for element in s(["script", "style", "footer", "nav", "header"]):
        element.decompose()
    body_text = s.get_text(separator=' ', strip=True)
    if meta_text:
        return meta_text + "\n\n" + body_text
    return body_text

async def fetch_page_tier3(url):
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            page = await context.new_page()
            await page.goto(url, wait_until='networkidle', timeout=15000)
            content = await page.content()
            await browser.close()
            return BeautifulSoup(content, 'html.parser')
    except ImportError:
        print("Playwright not installed.", file=sys.stderr)
    except Exception as e:
        print(f"Playwright fetch failed for {url}: {e}", file=sys.stderr)
    return None

async def fetch_page(http_client, url, headers):
    soup = None
    try:
        response = await http_client.get(url, headers=headers)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
    except Exception:
        pass
        
    if soup:
        text = clean_soup_text(soup)
        if len(text) >= 300:
            return soup
            
    print(f"Visible text sparse. Falling back to Tier 3 (Playwright) for {url}", file=sys.stderr)
    pw_soup = await fetch_page_tier3(url)
    if pw_soup:
        return pw_soup
        
    return soup

KEYWORD_PRIORITY = {
    "about": 100, "about-us": 100, "om": 100, "om-oss": 100,
    "company": 90, "company-profile": 90, "who-we-are": 90,
    "our-company": 90, "our-story": 90, "virksomhet": 90,
    "what-we-do": 80, "services": 80, "products": 80,
    "solutions": 80, "tjenester": 80, "produkter": 80,
    "mission": 70, "vision": 70,
    "team": 60, "leadership": 60, "ledelse": 60,
    "kontakt": 20, "contact": 20
}

NEGATIVE_KEYWORDS = [
    "blog", "article", "news", "newsroom", "press",
    "communication", "privacy", "terms", "career",
    "events", "personvern", "vilkår", "nyheter", "blogg", "kommunikasjon"
]

def score_link(href, text, title, aria):
    combined_text = f"{text} {title} {aria}".strip().lower()
    href_lower = href.lower()
    
    if any(nk in href_lower for nk in NEGATIVE_KEYWORDS) or any(nk in combined_text for nk in NEGATIVE_KEYWORDS):
        return -1
        
    max_score = 0
    for k, v in KEYWORD_PRIORITY.items():
        if k in ['om', 'team', 'about']:
            if re.search(rf'\b{k}\b', combined_text) or re.search(rf'/{k}(/|$|\?|#|-)', href_lower):
                if v > max_score:
                    max_score = v
        else:
            if k in href_lower or k in combined_text:
                if v > max_score:
                    max_score = v
                    
    if max_score > 0:
        return max_score - (len(href) / 1000.0)
    return 0

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
                print(f"Website fetch failed for {profile.orgnr}", file=sys.stderr)
                return profile
            
            scored_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text()
                title = a.get('title', '')
                aria = a.get('aria-label', '')
                score = score_link(href, text, title, aria)
                if score > 0:
                    full_url = urljoin(url, href)
                    if full_url.startswith('http'):
                        candidate_domain = urlparse(full_url).netloc.lower()
                        if candidate_domain == base_domain and full_url != url:
                            scored_links.append((score, full_url))
            
            if not scored_links:
                sitemap_url = urljoin(url, '/sitemap.xml')
                try:
                    sm_resp = await http_client.get(sitemap_url, timeout=5.0)
                    if sm_resp.status_code == 200:
                        urls = re.findall(r'<loc>(.*?)</loc>', sm_resp.text)
                        for u in urls:
                            score = score_link(u, "", "", "")
                            if score > 0:
                                candidate_domain = urlparse(u).netloc.lower()
                                if candidate_domain == base_domain and u != url:
                                    scored_links.append((score, u))
                except:
                    pass

            scored_links.sort(key=lambda x: x[0], reverse=True)
            links_to_fetch = []
            for score, link in scored_links:
                if link not in links_to_fetch:
                    links_to_fetch.append(link)
                    if len(links_to_fetch) >= 2:
                        break
            
            MAX_HOMEPAGE_CHARS = 3000
            MAX_SUBPAGE_CHARS = 5000
            
            texts = [f"--- URL: {url} ---\n{clean_soup_text(soup)[:MAX_HOMEPAGE_CHARS]}"]
                            
            for l in links_to_fetch:
                sub_soup = await fetch_page(http_client, l, headers)
                if sub_soup:
                    page_text = clean_soup_text(sub_soup)
                    texts.append(f"--- URL: {l} ---\n{page_text[:MAX_SUBPAGE_CHARS]}")
                    
            combined_text = "\n\n".join(texts)
            allowed_urls = {url} | set(links_to_fetch)
            
            prompt = f"""
            You are extracting factual information from a company's public website.
            
            Extract:
            1. mission_statement:
               - Only provide an explicit statement of what the organization/company exists to achieve, its purpose, mission, or stated objective.
               - Do not infer or invent a mission.
            2. company_description:
               - Provide a factual description of what the organization/company does, its products/services, or its business activities.
               
            IMPORTANT:
            - The organization may be a sole proprietorship, small company, clinic, consultancy, professional practice, etc.
            - A mission statement is optional.
            - A company description is useful when the website clearly describes the organization's activities, even if it does not use the words "mission" or "about us".
            - Do not confuse an individual's biography with the company's description.
            - Do not infer a mission from the person's opinions or unrelated articles.
            - If the evidence is genuinely absent, return null.
            - Every non-null field MUST use an exact URL from the supplied source pages.
            
            Allowed source URLs: {allowed_urls}
            
            Website content: 
            {combined_text}
            """
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    res_text = ""
                    if LLM_BACKEND == "ollama":
                        ollama_client = ollama.AsyncClient()
                        response = await ollama_client.chat(
                            model=OLLAMA_MODEL,
                            messages=[{'role': 'user', 'content': prompt}],
                            format=WebsiteFacts.model_json_schema(),
                            options={'temperature': 0.0}
                        )
                        res_text = response['message']['content']
                    else:
                        res = await client.aio.models.generate_content(
                            model='gemini-3.8-flash',
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                                response_schema=WebsiteFacts,
                                temperature=0.0,
                            ),
                        )
                        res_text = res.text
                    
                    result = WebsiteFacts.model_validate_json(res_text)
                    timestamp = datetime.now(timezone.utc)
                    
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
                            print(f"Rate limited on {profile.orgnr}. Waiting {wait_time}s...", file=sys.stderr)
                            await asyncio.sleep(wait_time)
                        else:
                            print(f"LLM Rate limit exhausted for {profile.orgnr}", file=sys.stderr)
                            break
                    else:
                        print(f"LLM extraction error for {profile.orgnr}: {repr(e)}", file=sys.stderr)
                        if attempt < max_retries - 1 and LLM_BACKEND == "ollama":
                            await asyncio.sleep(2)
                            continue
                        break
                        
        except Exception as e:
            print(f"Website scraping error for {profile.orgnr}: {repr(e)}", file=sys.stderr)
            
    return profile
