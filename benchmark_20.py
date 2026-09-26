import os
import json
import httpx
import asyncio
import re
import time
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from pydantic import BaseModel
import ollama

class FactExtraction(BaseModel):
    value: str
    source_url: str

class WebsiteFacts(BaseModel):
    mission_statement: FactExtraction | None = None
    company_description: FactExtraction | None = None

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
    except Exception as e:
        return None

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
                if v > max_score: max_score = v
        else:
            if k in href_lower or k in combined_text:
                if v > max_score: max_score = v
                    
    if max_score > 0:
        return max_score - (len(href) / 1000.0)
    return 0

async def run_benchmark():
    test_companies = []
    try:
        with open('submission_profiles.jsonl', 'r', encoding='utf-8') as f:
            for line in f:
                record = json.loads(line)
                facts = record.get('facts', {})
                if 'website' in facts:
                    test_companies.append({
                        "orgnr": record['orgnr'],
                        "website_url": facts['website']['value']
                    })
                    if len(test_companies) >= 20:
                        break
    except FileNotFoundError:
        print("submission_profiles.jsonl not found.")
        return
        
    if not test_companies:
        print("Could not find websites.")
        return

    ollama_client = ollama.AsyncClient()
    results = []

    print("Starting 20-company benchmark...\n")
    
    for idx, company in enumerate(test_companies, 1):
        orgnr = company["orgnr"]
        website_url = company["website_url"]
        print(f"[{idx}/20] Processing {orgnr} - {website_url}")
        
        record = {
            "Organization": orgnr,
            "Website": website_url,
            "HTTP status": None,
            "Initial text length": 0,
            "Playwright triggered?": "N",
            "Rendered text length": 0,
            "Relevant subpages found": 0,
            "LLM extraction time": 0,
            "Mission populated?": "N",
            "Description populated?": "N",
            "Mission source URL valid?": "N/A",
            "Description source URL valid?": "N/A",
            "Schema validation passed?": "N",
            "Error": None
        }
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        base_domain = urlparse(website_url).netloc.lower()
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as http_client:
            soup = None
            try:
                response = await http_client.get(website_url, headers=headers)
                record["HTTP status"] = response.status_code
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
            except Exception as e:
                record["Error"] = f"HTTP fetch error: {repr(e)}"
                
            if soup:
                initial_text = clean_soup_text(soup)
                record["Initial text length"] = len(initial_text)
                if len(initial_text) < 300:
                    record["Playwright triggered?"] = "Y"
                    pw_soup = await fetch_page_tier3(website_url)
                    if pw_soup:
                        soup = pw_soup
                        rendered_text = clean_soup_text(soup)
                        record["Rendered text length"] = len(rendered_text)
                    else:
                        record["Error"] = "Playwright fallback failed to get content."
            
            if not soup:
                results.append(record)
                continue
                
            scored_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text()
                title = a.get('title', '')
                aria = a.get('aria-label', '')
                score = score_link(href, text, title, aria)
                if score > 0:
                    full_url = urljoin(website_url, href)
                    if full_url.startswith('http'):
                        candidate_domain = urlparse(full_url).netloc.lower()
                        if candidate_domain == base_domain and full_url != website_url:
                            scored_links.append((score, full_url))
            
            if not scored_links:
                sitemap_url = urljoin(website_url, '/sitemap.xml')
                try:
                    sm_resp = await http_client.get(sitemap_url, timeout=5.0)
                    if sm_resp.status_code == 200:
                        urls = re.findall(r'<loc>(.*?)</loc>', sm_resp.text)
                        for u in urls:
                            score = score_link(u, "", "", "")
                            if score > 0:
                                candidate_domain = urlparse(u).netloc.lower()
                                if candidate_domain == base_domain and u != website_url:
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
            
            record["Relevant subpages found"] = len(links_to_fetch)
            
            MAX_HOMEPAGE_CHARS = 3000
            MAX_SUBPAGE_CHARS = 5000
            
            texts = [f"--- URL: {website_url} ---\n{clean_soup_text(soup)[:MAX_HOMEPAGE_CHARS]}"]
            
            for l in links_to_fetch:
                try:
                    sub_response = await http_client.get(l, headers=headers)
                    if sub_response.status_code == 200:
                        sub_soup = BeautifulSoup(sub_response.text, "html.parser")
                        sub_text = clean_soup_text(sub_soup)
                        texts.append(f"--- URL: {l} ---\n{sub_text[:MAX_SUBPAGE_CHARS]}")
                except:
                    pass
                    
            combined_text = "\n\n".join(texts)
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
            
            t0 = time.time()
            try:
                response = await ollama_client.chat(
                    model="qwen3:14b",
                    messages=[{'role': 'user', 'content': prompt}],
                    format=WebsiteFacts.model_json_schema(),
                    options={'temperature': 0.0}
                )
                dt = time.time() - t0
                record["LLM extraction time"] = round(dt, 2)
                
                res_text = response['message']['content']
                result = WebsiteFacts.model_validate_json(res_text)
                record["Schema validation passed?"] = "Y"
                
                if result.mission_statement:
                    record["Mission populated?"] = "Y"
                    valid = result.mission_statement.source_url in allowed_urls
                    record["Mission source URL valid?"] = "Y" if valid else "N"
                    if not valid:
                        record["Error"] = f"Invalid mission URL: {result.mission_statement.source_url}"
                
                if result.company_description:
                    record["Description populated?"] = "Y"
                    valid = result.company_description.source_url in allowed_urls
                    record["Description source URL valid?"] = "Y" if valid else "N"
                    if not valid:
                        err = f"Invalid description URL: {result.company_description.source_url}"
                        record["Error"] = record["Error"] + "; " + err if record["Error"] else err
                        
            except Exception as e:
                dt = time.time() - t0
                record["LLM extraction time"] = round(dt, 2)
                record["Error"] = f"LLM/Schema Error: {repr(e)}"
                
        results.append(record)

    # Print Report
    print("\n\n" + "="*80)
    print("BENCHMARK REPORT")
    print("="*80)
    
    for r in results:
        print(f"\nOrganization: {r['Organization']}")
        print(f"Website: {r['Website']}")
        print(f"HTTP status: {r['HTTP status']}")
        print(f"Initial text length: {r['Initial text length']}")
        print(f"Playwright triggered?: {r['Playwright triggered?']}")
        print(f"Rendered text length: {r['Rendered text length']}")
        print(f"Relevant subpages found: {r['Relevant subpages found']}")
        print(f"LLM extraction time: {r['LLM extraction time']}s")
        print(f"Mission populated?: {r['Mission populated?']}")
        print(f"Description populated?: {r['Description populated?']}")
        print(f"Mission source URL valid?: {r['Mission source URL valid?']}")
        print(f"Description source URL valid?: {r['Description source URL valid?']}")
        print(f"Schema validation passed?: {r['Schema validation passed?']}")
        if r['Error']:
            print(f"Error: {r['Error']}")
            
    # Aggregates
    avail = sum(1 for r in results if (r['Initial text length'] >= 300 or r['Rendered text length'] >= 300))
    mission_cov = sum(1 for r in results if r['Mission populated?'] == 'Y')
    desc_cov = sum(1 for r in results if r['Description populated?'] == 'Y')
    both_cov = sum(1 for r in results if r['Mission populated?'] == 'Y' and r['Description populated?'] == 'Y')
    
    total_prov = 0
    valid_prov = 0
    for r in results:
        if r['Mission populated?'] == 'Y':
            total_prov += 1
            if r['Mission source URL valid?'] == 'Y': valid_prov += 1
        if r['Description populated?'] == 'Y':
            total_prov += 1
            if r['Description source URL valid?'] == 'Y': valid_prov += 1
    
    schema_failures = sum(1 for r in results if r['Schema validation passed?'] == 'N' and r['HTTP status'] == 200)
    
    llm_times = [r['LLM extraction time'] for r in results if r['LLM extraction time'] > 0]
    avg_time = sum(llm_times) / len(llm_times) if llm_times else 0
    
    print("\n" + "="*80)
    print("AGGREGATE METRICS")
    print(f"Total Tested: {len(results)}")
    print(f"Website content availability: {avail}/{len(results)}")
    print(f"Mission coverage: {mission_cov}/{len(results)}")
    print(f"Description coverage: {desc_cov}/{len(results)}")
    print(f"Both-fields coverage: {both_cov}/{len(results)}")
    print(f"Provenance validity: {valid_prov}/{total_prov if total_prov > 0 else 1}")
    print(f"Schema failure rate: {schema_failures}/{len(results)}")
    print(f"Average LLM extraction time: {avg_time:.2f}s")
    print("="*80 + "\n")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
