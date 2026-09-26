import httpx
import json
import sys

def main():
    # Load existing ones to avoid overlap
    existing = set()
    try:
        with open("submission_profiles.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                existing.add(data["orgnr"])
    except:
        pass

    url = "https://data.brreg.no/enhetsregisteret/api/enheter?organisasjonsform=AS,ASA&size=100&page=50"
    print("Fetching novel companies from BRREG...", file=sys.stderr)
    resp = httpx.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = resp.json()
    
    unseen = []
    for enhet in data["_embedded"]["enheter"]:
        orgnr = enhet["organisasjonsnummer"]
        if orgnr not in existing:
            unseen.append(orgnr)
            if len(unseen) == 30:
                break
                
    with open("unseen_input.json", "w", encoding="utf-8") as f:
        json.dump(unseen, f)
        
    print(f"Saved {len(unseen)} completely novel org numbers to unseen_input.json", file=sys.stderr)

if __name__ == "__main__":
    main()
