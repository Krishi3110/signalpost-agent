import json

def validate_dataset(filepath="submission_profiles.jsonl"):
    print(f"Validating {filepath}...")
    
    valid_count = 0
    orgnrs = set()
    errors = []
    
    coverage = {
        "revenue": 0,
        "executive_team": 0,
        "mission_statement": 0,
        "company_description": 0
    }

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    errors.append(f"Line {line_num}: Invalid JSON")
                    continue
                
                orgnr = record.get("orgnr", "")
                if len(orgnr) != 9 or not orgnr.isdigit():
                    errors.append(f"Line {line_num}: Invalid orgnr format '{orgnr}'")
                    
                if orgnr in orgnrs:
                    errors.append(f"Line {line_num}: Duplicate orgnr '{orgnr}'")
                orgnrs.add(orgnr)
                
                if "company_name" not in record:
                    errors.append(f"Line {line_num}: Missing company_name")
                    
                facts = record.get("facts", {})
                for fact_key, fact_data in facts.items():
                    if "source_url" not in fact_data or "fetched_at" not in fact_data:
                        errors.append(f"Line {line_num}: Fact '{fact_key}' missing provenance")

                if "revenue" in facts: coverage["revenue"] += 1
                if "executive_team" in facts: coverage["executive_team"] += 1
                if "mission_statement" in facts: coverage["mission_statement"] += 1
                if "company_description" in facts: coverage["company_description"] += 1

                valid_count += 1
                
    except FileNotFoundError:
        print("Dataset file not found.")
        return

    print("-" * 30)
    print(f"Total lines processed: {valid_count}")
    print(f"Total unique organizations: {len(orgnrs)}")
    
    if errors:
        print(f"Found {len(errors)} errors:")
        for e in errors[:10]:
            print(f"  - {e}")
    else:
        print(f"Dataset validation passed. {valid_count} valid organizations. 0 schema/provenance errors.")
        
    print("\nCoverage Report:")
    print(f"  revenue: {coverage['revenue']}/{valid_count}")
    print(f"  executive_team: {coverage['executive_team']}/{valid_count}")
    print(f"  mission_statement: {coverage['mission_statement']}/{valid_count}")
    print(f"  company_description: {coverage['company_description']}/{valid_count}")
        
    if valid_count >= 1000 and len(errors) == 0:
        print("\nREADY FOR SUBMISSION! 🚀")
    else:
        print("\nCriteria NOT met. Do not submit yet.")

if __name__ == "__main__":
    validate_dataset()
