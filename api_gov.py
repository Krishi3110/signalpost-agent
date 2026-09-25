import httpx
from datetime import datetime, timezone
from models import Fact, CompanyProfile

async def fetch_brreg_basic_info(orgnr: str) -> CompanyProfile | None:
    """Fetches deterministic company data from the official Brreg API."""
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
    
    # Add a strict 10-second timeout
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            
            if response.status_code != 200:
                return None
                
            data = response.json()
            timestamp = datetime.now(timezone.utc)
            
            def create_fact(value) -> Fact:
                return Fact(value=value, source_url=url, fetched_at=timestamp)
            
            name = data.get("navn")
            if not name:
                return None
                
            profile = CompanyProfile(
                orgnr=orgnr,
                company_name=create_fact(name)
            )
            
            if "organisasjonsform" in data:
                profile.facts["org_form"] = create_fact(data["organisasjonsform"].get("kode"))
                
            if "registreringsdatoEnhetsregisteret" in data:
                profile.facts["registration_date"] = create_fact(data["registreringsdatoEnhetsregisteret"])
                
            if "forretningsadresse" in data:
                addr = data["forretningsadresse"]
                address_str = f"{', '.join(addr.get('adresse', []))}, {addr.get('postnummer', '')} {addr.get('poststed', '')}".strip(', ')
                if address_str != ",":
                    profile.facts["business_address"] = create_fact(address_str)
                
            if "hjemmeside" in data:
                website = data["hjemmeside"]
                if not website.startswith("http"):
                    website = f"https://{website}"
                profile.facts["website"] = create_fact(website)
                
            if "antallAnsatte" in data:
                profile.facts["employee_count"] = create_fact(data["antallAnsatte"])
                
            # --- NEW DETERMINISTIC FIELDS ---
            if "postadresse" in data:
                addr = data["postadresse"]
                address_str = f"{', '.join(addr.get('adresse', []))}, {addr.get('postnummer', '')} {addr.get('poststed', '')}".strip(', ')
                if address_str and address_str != ",":
                    profile.facts["postal_address"] = create_fact(address_str)
                    
            if "registrertIMvaregisteret" in data:
                profile.facts["vat_registered"] = create_fact(data["registrertIMvaregisteret"])
                
            if "naeringskode1" in data:
                profile.facts["nace_code"] = create_fact(data["naeringskode1"].get("kode"))
                profile.facts["nace_description"] = create_fact(data["naeringskode1"].get("beskrivelse"))
                
            # Aggregate company status flags
            status_flags = []
            if data.get("underAvvikling"): status_flags.append("Under liquidation")
            if data.get("konkurs"): status_flags.append("Bankrupt")
            if data.get("underTvangsavviklingEllerTvangsopplosning"): status_flags.append("Under forced liquidation")
            
            profile.facts["company_status"] = create_fact(", ".join(status_flags) if status_flags else "Active")
                
            return profile
            
        except httpx.RequestError:
            # Silently catch timeouts so they don't crash the entire batch run
            return None

async def fetch_brreg_financials(profile: CompanyProfile) -> CompanyProfile:
    """Fetches financial data and appends it to the existing company profile."""
    # Using the challenge-specified 2026 endpoint for final submission
    url = f"https://data.brreg.no/regnskapsregisteret/2026/regnskaper/{profile.orgnr}"
    # url = f"https://data.brreg.no/regnskapsregisteret/regnskap/{profile.orgnr}"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            
            # If financial data is missing or unauthorized, fail safely by returning the profile as-is
            if response.status_code != 200:
                return profile
                
            data = response.json()
            
            # The API might return a list of annual reports; grab the first/latest one
            report = data[0] if isinstance(data, list) and len(data) > 0 else data
            timestamp = datetime.now(timezone.utc)
            
            def create_fact(value) -> Fact:
                return Fact(value=value, source_url=url, fetched_at=timestamp)
                
            # Safely navigate the standard Brreg nested JSON structure for financials
            if "egenkapitalGjeld" in report:
                debt = report["egenkapitalGjeld"].get("gjeldOversikt", {}).get("sumGjeld")
                if debt is not None:
                    profile.facts["total_debt"] = create_fact(debt)
            
            if "eiendeler" in report:
                assets = report["eiendeler"].get("sumEiendeler")
                if assets is not None:
                    profile.facts["total_assets"] = create_fact(assets)
                    
            if "resultatregnskapResultat" in report:
                res = report["resultatregnskapResultat"]
                revenue = res.get("driftsresultat", {}).get("driftsinntekter", {}).get("sumDriftsinntekter")
                op_profit = res.get("driftsresultat", {}).get("driftsresultat")
                
                if revenue is not None:
                    profile.facts["revenue"] = create_fact(revenue)
                if op_profit is not None:
                    profile.facts["operating_profit"] = create_fact(op_profit)
                    
        except (httpx.RequestError, KeyError, AttributeError, IndexError):
            # Strict guardrail: Do not guess if parsing fails
            pass 
            
        return profile
