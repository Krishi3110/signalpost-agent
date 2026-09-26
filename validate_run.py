import json
import sys

def validate(input_file, output_file, stdout_file):
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            inputs = json.load(f)
    except Exception as e:
        print(f"Failed to load input: {e}")
        return

    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            output_lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Failed to load output: {e}")
        return
        
    try:
        with open(stdout_file, 'r', encoding='utf-8') as f:
            stdout_lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Failed to load stdout: {e}")
        return

    print("--- VALIDATION REPORT ---")
    
    # 1. Line counts
    print(f"Input orgs: {len(inputs)}")
    print(f"Output lines: {len(output_lines)}")
    print(f"Stdout lines: {len(stdout_lines)}")
    if len(output_lines) != len(inputs):
        print("❌ FAILED: Output line count does not match input count!")
    else:
        print("✅ SUCCESS: Output line count matches exactly.")
        
    if len(stdout_lines) != len(inputs):
        print("❌ FAILED: Stdout line count does not match input count (stdout is dirty!).")
    else:
        print("✅ SUCCESS: Stdout line count matches exactly.")

    # 2. JSON & Envelope Validation
    allowed_states = {"available", "not_available", "blocked", "not_applicable", "ambiguous", "failed"}
    output_orgs = []
    
    malformed_json = 0
    invalid_schema = 0
    invalid_state = 0
    
    for i, line in enumerate(stdout_lines):
        try:
            data = json.loads(line)
            if 'orgnr' not in data or 'state' not in data:
                invalid_schema += 1
                continue
            output_orgs.append(data['orgnr'])
            if data['state'] not in allowed_states:
                invalid_state += 1
        except json.JSONDecodeError:
            malformed_json += 1
            
    if malformed_json > 0:
        print(f"❌ FAILED: {malformed_json} lines are not valid JSON.")
    else:
        print("✅ SUCCESS: Every stdout line is valid JSON.")
        
    if invalid_schema > 0:
        print(f"❌ FAILED: {invalid_schema} lines are missing 'orgnr' or 'state'.")
    else:
        print("✅ SUCCESS: Every stdout line fits the ResultEnvelope schema.")
        
    if invalid_state > 0:
        print(f"❌ FAILED: {invalid_state} lines have an invalid state.")
    else:
        print("✅ SUCCESS: Every state is within the 6 allowed evaluator states.")
        
    # 3. Input mapping
    missing_orgs = set(inputs) - set(output_orgs)
    extra_orgs = set(output_orgs) - set(inputs)
    
    if len(output_orgs) != len(set(output_orgs)):
        print("❌ FAILED: Duplicate organization numbers found in the output.")
    else:
        print("✅ SUCCESS: No duplicate organization numbers.")
        
    if missing_orgs or extra_orgs:
        print(f"❌ FAILED: Organization IDs do not match perfectly.")
        if missing_orgs: print(f"   Missing: {list(missing_orgs)[:5]}...")
        if extra_orgs: print(f"   Extra: {list(extra_orgs)[:5]}...")
    else:
        print("✅ SUCCESS: Output organization numbers perfectly match the 100 inputs.")
        
    if output_orgs != inputs:
        print("❌ FAILED: Output ordering does not perfectly match input ordering.")
    else:
        print("✅ SUCCESS: Output ordering is deterministic and matches inputs exactly.")
        
if __name__ == '__main__':
    if len(sys.argv) != 4:
        print("Usage: python validate_run.py <input.json> <output.jsonl> <stdout.txt>")
        sys.exit(1)
    validate(sys.argv[1], sys.argv[2], sys.argv[3])
