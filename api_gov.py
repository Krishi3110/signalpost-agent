import httpx
import asyncio
from datetime import datetime, timezone
from models import Fact, CompanyProfile

# Polite headers prevent the government firewall from dropping connections
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Signalpost/1.0'}

async def fetch_brreg_basic_info(orgnr: str) -> CompanyProfile | None:
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, headers=HEADERS)
                if response.status_code != 200:
                    if attempt == 2: print(f"Gov API failed for {orgnr}: {response.status_code}")
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
                data = response.json()
                timestamp = datetime.now(timezone.utc)
                
                def create_fact(value) -> Fact:
                    return Fact(value=value, source_url=url, fetched_at=timestamp)
                
                name = data.get("navn")
                if not name: return None
                    
                profile = CompanyProfile(orgnr=orgnr, company_name=create_fact(name))
                
                if "organisasjonsform" in data: profile.facts["org_form"] = create_fact(data["organisasjonsform"].get("kode"))
                if "registreringsdatoEnhetsregisteret" in data: profile.facts["registration_date"] = create_fact(data["registreringsdatoEnhetsregisteret"])
                if "forretningsadresse" in data:
                    addr = data["forretningsadresse"]
                    address_str = f"{', '.join(addr.get('adresse', []))}, {addr.get('postnummer', '')} {addr.get('poststed', '')}".strip(', ')
                    if address_str != ",": profile.facts["business_address"] = create_fact(address_str)
                if "hjemmeside" in data:
                    website = data["hjemmeside"]
                    if not website.startswith("http"): website = f"https://{website}"
                    profile.facts["website"] = create_fact(website)
                if "antallAnsatte" in data: profile.facts["employee_count"] = create_fact(data["antallAnsatte"])
                if "postadresse" in data:
                    addr = data["postadresse"]
                    address_str = f"{', '.join(addr.get('adresse', []))}, {addr.get('postnummer', '')} {addr.get('poststed', '')}".strip(', ')
                    if address_str and address_str != ",": profile.facts["postal_address"] = create_fact(address_str)
                if "registrertIMvaregisteret" in data: profile.facts["vat_registered"] = create_fact(data["registrertIMvaregisteret"])
                if "naeringskode1" in data:
                    profile.facts["nace_code"] = create_fact(data["naeringskode1"].get("kode"))
                    profile.facts["nace_description"] = create_fact(data["naeringskode1"].get("beskrivelse"))
                    
                status_flags = []
                if data.get("underAvvikling"): status_flags.append("Under liquidation")
                if data.get("konkurs"): status_flags.append("Bankrupt")
                if data.get("underTvangsavviklingEllerTvangsopplosning"): status_flags.append("Under forced liquidation")
                profile.facts["company_status"] = create_fact(", ".join(status_flags) if status_flags else "Active")
                    
                return profile
            except Exception as e:
                if attempt == 2: print(f"Gov API error for {orgnr}: {repr(e)}")
                await asyncio.sleep(2 ** attempt)
        return None

async def fetch_brreg_financials(profile: CompanyProfile) -> CompanyProfile:
    url = f"https://data.brreg.no/regnskapsregisteret/regnskap/{profile.orgnr}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, headers=HEADERS)
                if response.status_code != 200:
                    if attempt == 2: print(f"Financial API failed for {profile.orgnr}: {response.status_code}")
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
                data = response.json()
                if not data: return profile
                    
                latest = data[0]
                timestamp = datetime.now(timezone.utc)
                
                def create_fact(value) -> Fact:
                    return Fact(value=value, source_url=url, fetched_at=timestamp)
                    
                # Recursive helper to hunt down the primitive numbers and ignore dicts
                def find_val(obj, key):
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            if k == key and isinstance(v, (int, float)): return v
                            res = find_val(v, key)
                            if res is not None: return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_val(item, key)
                            if res is not None: return res
                    return None
                
                op_prof = find_val(latest, "driftsresultat")
                rev = find_val(latest, "sumDriftsinntekter")
                if rev is None: rev = find_val(latest, "salgsinntekter")
                debt = find_val(latest, "sumGjeld")
                assets = find_val(latest, "sumEgenkapitalGjeld")
                
                if op_prof is not None: profile.facts["operating_profit"] = create_fact(op_prof)
                if rev is not None: profile.facts["revenue"] = create_fact(rev)
                if debt is not None: profile.facts["total_debt"] = create_fact(debt)
                if assets is not None: profile.facts["total_assets"] = create_fact(assets)
                
                break # Success, exit retry loop
                    
            except Exception as e:
                if attempt == 2: print(f"Financial parsing error for {profile.orgnr}: {repr(e)}")
                await asyncio.sleep(2 ** attempt)
                
    return profile

async def fetch_brreg_roles(profile: CompanyProfile) -> CompanyProfile:
    url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.orgnr}/roller"
    
    EXECUTIVE_ROLE_KEYWORDS = (
        "daglig leder", "administrerende direktør", "adm.direktør",
        "styrets leder", "styreleder", "nestleder",
        "styremedlem", "varamedlem", "observatør",
    )
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for attempt in range(3):
            try:
                response = await client.get(url, headers=HEADERS)
                if response.status_code == 404:
                    return profile # No roles endpoint or no roles found
                if response.status_code != 200:
                    if attempt == 2: print(f"Roles API failed for {profile.orgnr}: {response.status_code}")
                    await asyncio.sleep(2 ** attempt)
                    continue
                    
                data = response.json()
                timestamp = datetime.now(timezone.utc)
                
                # Check for "rollegrupper" (newer BRREG format returns a dict with it, older is a list directly)
                rollegrupper = data.get("rollegrupper", []) if isinstance(data, dict) else data
                if not isinstance(rollegrupper, list):
                    print(f"Unexpected rollegrupper format for {profile.orgnr}")
                    return profile
                    
                role_entries = []
                for group in rollegrupper:
                    if not isinstance(group, dict): continue
                    roller = group.get("roller", [])
                    if not isinstance(roller, list): continue
                    
                    for role in roller:
                        if not isinstance(role, dict): continue
                        if role.get("avregistrert") is True: continue
                        
                        role_type = role.get("type", {})
                        if not isinstance(role_type, dict): role_type = {}
                        role_title = role_type.get("beskrivelse") or role_type.get("kode") or "Unknown role"
                        
                        title_lower = str(role_title).lower()
                        if not any(keyword in title_lower for keyword in EXECUTIVE_ROLE_KEYWORDS):
                            continue
                            
                        name = None
                        
                        # PERSON ROLE
                        person = role.get("person")
                        if isinstance(person, dict):
                            person_name = person.get("navn")
                            if isinstance(person_name, dict):
                                parts = [
                                    person_name.get("fornavn"),
                                    person_name.get("mellomnavn"),
                                    person_name.get("etternavn")
                                ]
                                parts = [str(part).strip() for part in parts if part]
                                if parts: name = " ".join(parts)
                            elif isinstance(person_name, str):
                                name = person_name.strip()
                                
                        # ENTITY ROLE
                        if not name:
                            entity = role.get("enhet")
                            if isinstance(entity, dict):
                                entity_name = entity.get("navn")
                                if isinstance(entity_name, list):
                                    entity_name = " ".join(str(x).strip() for x in entity_name if x)
                                elif isinstance(entity_name, str):
                                    entity_name = entity_name.strip()
                                if entity_name: name = entity_name
                                
                        # ADMINISTRATOR ROLE
                        if not name:
                            administrator = role.get("bostyrer")
                            if isinstance(administrator, dict):
                                admin_name = administrator.get("navn")
                                if isinstance(admin_name, str):
                                    name = admin_name.strip()
                                    
                        if name:
                            role_entries.append(f"{name} — {role_title}")
                            
                if role_entries:
                    profile.facts["executive_team"] = Fact(
                        value="; ".join(role_entries),
                        source_url=url,
                        fetched_at=timestamp
                    )
                break
            except Exception as e:
                if attempt == 2: print(f"Roles parsing error for {profile.orgnr}: {repr(e)}")
                await asyncio.sleep(2 ** attempt)
                
    return profile
