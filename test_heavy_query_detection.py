#!/usr/bin/env python3
"""
Test script for heavy query detection
"""
import re

def is_heavy_query(query: str) -> bool:
    """
    Detect queries that require listing multiple items or complex responses.
    """
    query_lower = query.lower().strip()

    # Patterns that indicate "list all" type queries
    heavy_patterns = [
        r'\b(todas?|todos?)\s+(las?|los?)\s+(promo|convenio|beneficio|servicio)',  # "todas las promos"
        r'\b(qu[eé]|cuales?|cuantas?)\s+(promo|convenio|beneficio|servicio)',  # "que promos hay"
        r'\b(hay|tienen?|ofrecen?)\s+(alguna?s?)?\s*(promo|convenio|beneficio)',  # "hay promos"
        r'\b(alg[uú]n)\s+(convenio|promo|beneficio)',  # "algún convenio"
        r'\b(lista|listar|mostrar|decir)\s+(las?|los?|todas?|todos?)',  # "lista todos"
        r'\b(que|cuales)\s+(son|hay)\s+(las?|los?)',  # "que son los convenios"
    ]

    for pattern in heavy_patterns:
        if re.search(pattern, query_lower):
            return True

    return False

# Test cases
test_queries = {
    # Heavy queries (should return True)
    "Heavy": [
        "que promos hay?",
        "Que promociones tienen?",
        "hay alguna promoción?",
        "todas las promociones",
        "todos los convenios",
        "que convenios hay?",
        "Hay algún convenio con empresas?",
        "cuales son los beneficios?",
        "que beneficios ofrecen?",
        "listar todos los servicios",
        "mostrar las promociones",
        "decir todos los convenios",
        "que son los convenios?",
        "cuales son las promos?",
    ],
    # Normal queries (should return False)
    "Normal": [
        "hola",
        "buenos dias",
        "como llegar al country?",
        "cual es el horario?",
        "cuanto cuesta?",
        "necesito un crédito",
        "como asociarme?",
        "quiero hablar con una persona",
        "cual es la tasa de interés?",
        "donde están ubicados?",
    ]
}

print("=" * 60)
print("HEAVY QUERY DETECTION TEST")
print("=" * 60)

errors = 0

print("\n✅ HEAVY QUERIES (should be detected):")
print("-" * 60)
for query in test_queries["Heavy"]:
    result = is_heavy_query(query)
    status = "✅" if result else "❌ FAILED"
    print(f"{status} '{query}' → {result}")
    if not result:
        errors += 1

print("\n⚡ NORMAL QUERIES (should NOT be detected):")
print("-" * 60)
for query in test_queries["Normal"]:
    result = is_heavy_query(query)
    status = "✅" if not result else "❌ FAILED"
    print(f"{status} '{query}' → {result}")
    if result:
        errors += 1

print("\n" + "=" * 60)
if errors == 0:
    print("✅ ALL TESTS PASSED!")
else:
    print(f"❌ {errors} TESTS FAILED")
print("=" * 60)
