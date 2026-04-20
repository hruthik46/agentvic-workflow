"""v7.23.1 — extend classify_error to extract structured 'category' field
directly via regex (catches arbitrary hyphenated categories agents emit).

Now matches: service-unavailable, port-not-listening, database-error,
env-misconfiguration, dns-failure, etc. — anything testers may emit.
"""
from pathlib import Path
import py_compile
import re

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Extend the hyphen map + add structured-extract pre-pass
OLD = '''    # v7.23-A: hyphenated category map (covers what testers actually emit)
    hyphen_map = {
        "syntax-error":            "coding",
        "compilation-error":       "coding",
        "build-failure":           "coding",
        "build-error":             "coding",
        "undefined-reference":     "coding",
        "undefined-symbol":        "coding",
        "type-mismatch":           "coding",
        "wrong-import":            "coding",
        "missing-dependency":      "coding",
        "logic-bug":               "coding",
        "api-contract-violation":  "api_contract_violation",
        "wrong-status-code":       "api_contract_violation",
        "missing-field":           "api_contract_violation",
        "wrong-field-type":        "api_contract_violation",
        "field-name-mismatch":     "api_contract_violation",
        "no-api-server":           "infra",
        "service-unreachable":     "infra",
        "deployment-failure":      "deployment",
        "race-condition":          "race_condition",
        "null-pointer":            "null_pointer",
        "off-by-one":              "off_by_one",
        "memory-leak":             "memory_leak",
        "timeout":                 "timeout_deadlock",
        "deadlock":                "timeout_deadlock",
        "state-corruption":        "state_corruption",
        "resource-exhaustion":     "resource_exhaustion",
        "data-loss-risk":          "data_loss_risk",
        "rollback-plan-missing":   "rollback_plan_missing",
    }
    # First try hyphenated forms (covers structured critical_issues category strings)
    for hyphen_cat, tax_cat in hyphen_map.items():
        if hyphen_cat in error_lower or hyphen_cat.replace("-", "_") in error_lower:
            cat_data = categories.get(tax_cat, categories.get("unknown", {}))
            return tax_cat, cat_data
'''

NEW = '''    # v7.23-A + v7.23.1: hyphenated category map (covers what testers actually emit)
    hyphen_map = {
        # coding errors
        "syntax-error":            "coding",
        "compilation-error":       "coding",
        "build-failure":           "coding",
        "build-error":             "coding",
        "undefined-reference":     "coding",
        "undefined-symbol":        "coding",
        "type-mismatch":           "coding",
        "wrong-import":            "coding",
        "missing-dependency":      "coding",
        "logic-bug":               "coding",
        # api contract
        "api-contract-violation":  "api_contract_violation",
        "wrong-status-code":       "api_contract_violation",
        "missing-field":           "api_contract_violation",
        "wrong-field-type":        "api_contract_violation",
        "field-name-mismatch":     "api_contract_violation",
        # infra / runtime
        "no-api-server":           "infra",
        "service-unreachable":     "infra",
        "service-unavailable":     "infra",
        "service-down":            "infra",
        "service-failed":          "infra",
        "service-crashed":         "infra",
        "service-restart-loop":    "infra",
        "port-not-listening":      "infra",
        "port-blocked":            "infra",
        "dns-failure":             "infra",
        "network-unreachable":     "infra",
        "database-error":          "infra",
        "database-unreachable":    "infra",
        "env-misconfiguration":    "infra",
        "config-error":            "infra",
        "missing-env-var":         "infra",
        "malformed-env":           "infra",
        # deployment
        "deployment-failure":      "deployment",
        "rollback-required":       "deployment",
        "image-pull-error":        "deployment",
        # concurrency / safety
        "race-condition":          "race_condition",
        "null-pointer":            "null_pointer",
        "off-by-one":              "off_by_one",
        "memory-leak":             "memory_leak",
        "timeout":                 "timeout_deadlock",
        "deadlock":                "timeout_deadlock",
        "state-corruption":        "state_corruption",
        "resource-exhaustion":     "resource_exhaustion",
        "data-loss-risk":          "data_loss_risk",
        "rollback-plan-missing":   "rollback_plan_missing",
    }

    # v7.23.1: extract 'category' field via regex from structured critical_issues
    # Input often looks like "{'category': 'service-unavailable', ...}" — pull out the value
    import re as _v7231_re
    _v7231_cats_extracted = _v7231_re.findall(r"'category'\\s*:\\s*'([a-z0-9\\-_]+)'", error_lower)
    _v7231_cats_extracted += _v7231_re.findall(r'"category"\\s*:\\s*"([a-z0-9\\-_]+)"', error_lower)
    for _v7231_c in _v7231_cats_extracted:
        if _v7231_c in hyphen_map:
            tax_cat = hyphen_map[_v7231_c]
            cat_data = categories.get(tax_cat, categories.get("unknown", {}))
            return tax_cat, cat_data
        # heuristic catch-all: hyphenated cat strings starting with these prefixes
        for _v7231_pref, _v7231_tax in [("service-", "infra"), ("port-", "infra"),
                                          ("database-", "infra"), ("env-", "infra"),
                                          ("network-", "infra"), ("dns-", "infra"),
                                          ("config-", "infra"), ("missing-env", "infra"),
                                          ("syntax-", "coding"), ("build-", "coding"),
                                          ("compile-", "coding"), ("type-", "coding"),
                                          ("undefined-", "coding"), ("wrong-status", "api_contract_violation"),
                                          ("missing-field", "api_contract_violation"),
                                          ("api-", "api_contract_violation"),
                                          ("deployment-", "deployment"),
                                          ("rollback-", "deployment"),
                                          ("race-", "race_condition"),
                                          ("null-", "null_pointer"),
                                          ("memory-", "memory_leak"),
                                          ("timeout", "timeout_deadlock"),
                                          ("deadlock", "timeout_deadlock"),
                                          ("data-loss", "data_loss_risk")]:
            if _v7231_c.startswith(_v7231_pref):
                cat_data = categories.get(_v7231_tax, categories.get("unknown", {}))
                return _v7231_tax, cat_data

    # Then try hyphenated forms (covers structured critical_issues category strings)
    for hyphen_cat, tax_cat in hyphen_map.items():
        if hyphen_cat in error_lower or hyphen_cat.replace("-", "_") in error_lower:
            cat_data = categories.get(tax_cat, categories.get("unknown", {}))
            return tax_cat, cat_data
'''

if "v7.23.1: extract 'category' field" in text:
    print("[v7.23.1] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.23.1] structured-category extractor + 16 new mappings + prefix heuristic wired")
else:
    print("[v7.23.1] WARN: OLD block not found exactly")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.23.1] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.23.1] SYNTAX ERROR: {e}")
