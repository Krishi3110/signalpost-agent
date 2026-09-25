import httpx
from datetime import datetime, timezone
from models import Fact, CompanyProfile

async def fetch_brreg_basic_info(orgnr: str) -> CompanyProfile | None:
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                print(f"Gov API failed for {orgnr}: {response.status_code}")
                return None
                
            data = response.json()
            timestamp = datetime.now(timezone.utc)
            
            def create_fact(value) -> Fact:
                return Fact(value=value, source_url=url, fetched_at=timestamp)
            
            name = data.get("navn")
            if not name:
                return None
                
            profile = CompanyProfile(orgnr=orgnr, company_name=create_fact(name))
            
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
                if not website.startswith("http"): website = f"https://{website}"
                profile.facts["website"] = create_fact(website)
            if "antallAnsatte" in data:
                profile.facts["employee_count"] = create_fact(data["antallAnsatte"])
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
                
            status_flags = []
            if data.get("underAvvikling"): status_flags.append("Under liquidation")
            if data.get("konkurs"): status_flags.append("Bankrupt")
            if data.get("underTvangsavviklingEllerTvangsopplosning"): status_flags.append("Under forced liquidation")
            profile.facts["company_status"] = create_fact(", ".join(status_flags) if status_flags else "Active")
                
            return profile
        except httpx.RequestError as e:
            print(f"Gov API timeout/error for {orgnr}: {e}")
            return None

async def fetch_brreg_financials(profile: CompanyProfile) -> CompanyProfile:
    url = f"https://data.brreg.no/regnskapsregisteret/2026/regnskaper/{profile.orgnr}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                print(f"Financial API failed for {profile.orgnr}: {response.status_code}")
                return profile
                
            data = response.json()
            if not data:
                return profile
                
            latest = data[0]
            timestamp = datetime.now(timezone.utc)
            
            def create_fact(value) -> Fact:
                return Fact(value=value, source_url=url, fetched_at=timestamp)
                
            res = latest.get("resultatregnskapResultat", {})
            bal = latest.get("egenkapitalGjeld", {})
            
            if "driftsresultat" in res:
                profile.facts["operating_profit"] = create_fact(res["driftsresultat"])
            if "salgsinntekter" in res:
                profile.facts["revenue"] = create_fact(res["salgsinntekter"])
            if "sumGjeld" in bal:
                profile.facts["total_debt"] = create_fact(bal["sumGjeld"])
            if "sumEgenkapitalGjeld" in bal:
                profile.facts["total_assets"] = create_fact(bal["sumEgenkapitalGjeld"])
                
        except Exception as e:
            print(f"Financial parsing error for {profile.orgnr}: {repr(e)}")
            
    return profile
