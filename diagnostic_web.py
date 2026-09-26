import os
import json
import httpx
import asyncio
import re
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from pydantic import BaseModel

class FactExtraction(BaseModel):
    value: str
    source_url: str

class WebsiteFacts(BaseModel):
    mission_statement: FactExtraction | None = None
    company_description: FactExtraction | None = None

def clean_soup_text(soup):
    for element in soup(["script", "style", "footer", "nav", "header"]):
        element.decompose()
    return soup.get_text(separator=' ', strip=True)

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

def score_link(href, text):
    href_lower = href.lower()
    text_lower = text.strip().lower()
    
    if any(nk in href_lower for nk in NEGATIVE_KEYWORDS) or any(nk in text_lower for nk in NEGATIVE_KEYWORDS):
        return -1
        
    max_score = 0
    for k, v in KEYWORD_PRIORITY.items():
        if k in ['om', 'team', 'about']:
            if re.search(rf'\b{k}\b', text_lower) or re.search(rf'/{k}(/|$|\?|#)', href_lower):
                if v > max_score:
                    max_score = v
        else:
            if k in href_lower or k in text_lower:
                if v > max_score:
                    max_score = v
                    
    if max_score > 0:
        # Tie-breaker: penalize long URLs to prefer top-level navigation
        return max_score - (len(href) / 1000.0)
    return 0

async def run_diagnostic():
    # Find 3 standard companies with websites, skipping the previous test case
    test_companies = []
    try:
        with open('submission_profiles.jsonl', 'r', encoding='utf-8') as f:
            for line in f:
                record = json.loads(line)
                facts = record.get('facts', {})
                if 'website' in facts:
                    orgnr = record['orgnr']
                    if orgnr == "924829214":
                        continue
                    website_url = facts['website']['value']
                    test_companies.append({"orgnr": orgnr, "website_url": website_url})
                    if len(test_companies) >= 3:
                        break
    except FileNotFoundError:
        print("submission_profiles.jsonl not found. Make sure you are in the right directory.")
        return
        
    if not test_companies:
        print("Could not find enough websites to test.")
        return

    import ollama
    ollama_client = ollama.AsyncClient()

    for idx, company in enumerate(test_companies, 1):
        orgnr = company["orgnr"]
        website_url = company["website_url"]
        
        print(f"\n======================================")
        print(f"=== TEST COMPANY {idx}/3: {orgnr} ===")
        print(f"Target URL: {website_url}")
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        base_domain = urlparse(website_url).netloc.lower()
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
            try:
                response = await http_client.get(website_url, headers=headers)
                print(f"HTTP Status: {response.status_code}")
                if response.status_code != 200:
                    print("Fetch failed. Skipping.")
                    continue
                soup = BeautifulSoup(response.text, "html.parser")
            except Exception as e:
                print(f"Fetch threw exception: {repr(e)}. Skipping.")
                continue
                
            print("\n--- LINK DISCOVERY ---")
            scored_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text().lower()
                score = score_link(href, text)
                if score > 0:
                    full_url = urljoin(website_url, href)
                    if full_url.startswith('http'):
                        candidate_domain = urlparse(full_url).netloc.lower()
                        if candidate_domain == base_domain and full_url != website_url:
                            scored_links.append((score, full_url))
            
            scored_links.sort(key=lambda x: x[0], reverse=True)
            links_to_fetch = []
            for score, link in scored_links:
                if link not in links_to_fetch:
                    links_to_fetch.append(link)
                    if len(links_to_fetch) >= 2:
                        break
                            
            print(f"Discovered {len(links_to_fetch)} highest-scoring subpages: {links_to_fetch}")
            
            print("\n--- CONTENT CLEANING & TRUNCATION ---")
            homepage_text = clean_soup_text(soup)
            print(f"Homepage raw text length: {len(homepage_text)} characters")
            
            MAX_HOMEPAGE_CHARS = 3000
            MAX_SUBPAGE_CHARS = 5000
            
            texts = [f"--- URL: {website_url} ---\n{homepage_text[:MAX_HOMEPAGE_CHARS]}"]
            
            for l in links_to_fetch:
                try:
                    sub_response = await http_client.get(l, headers=headers)
                    if sub_response.status_code == 200:
                        sub_soup = BeautifulSoup(sub_response.text, "html.parser")
                        sub_text = clean_soup_text(sub_soup)
                        print(f"  -> Subpage '{l}' text length: {len(sub_text)} chars")
                        texts.append(f"--- URL: {l} ---\n{sub_text[:MAX_SUBPAGE_CHARS]}")
                    else:
                        print(f"  -> Subpage '{l}' failed: HTTP {sub_response.status_code}")
                except Exception as e:
                    print(f"  -> Subpage '{l}' fetch threw exception: {repr(e)}")
                    
            combined_text = "\n\n".join(texts)
            print(f"Total combined text length sent to LLM: {len(combined_text)} characters")
            
            print("\n--- OLLAMA EXTRACTION ---")
            allowed_urls = {website_url} | set(links_to_fetch)
            
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
            
            try:
                response = await ollama_client.chat(
                    model="qwen3:14b",
                    messages=[{'role': 'user', 'content': prompt}],
                    format=WebsiteFacts.model_json_schema(),
                    options={'temperature': 0.0}
                )
                
                res_text = response['message']['content']
                result = WebsiteFacts.model_validate_json(res_text)
                
                print("\n--- VALIDATION & PROVENANCE ---")
                if result.mission_statement:
                    print(f"Mission: {result.mission_statement.value}")
                    print(f"Mission URL: {result.mission_statement.source_url}")
                else:
                    print("Mission: None")
                    
                if result.company_description:
                    print(f"Description: {result.company_description.value}")
                    print(f"Description URL: {result.company_description.source_url}")
                else:
                    print("Description: None")
                    
            except Exception as e:
                print(f"Ollama execution failed: {repr(e)}")

if __name__ == "__main__":
    asyncio.run(run_diagnostic())
