#!/usr/bin/env python3
"""
Evaluador del chatbot de la Cooperativa Nazareth.

Corre las preguntas de tests/eval_cases.json contra la cadena RAG real y verifica
que cada respuesta cumpla lo esperado:

  - must_contain      : todos estos textos DEBEN aparecer en la respuesta.
  - must_not_contain  : ninguno de estos textos debe aparecer.
  - expect_fallback   : la respuesta debe ser la derivación de la regla 3.1
                        (contiene alguno de los fallback_markers, p.ej. "552631").

Uso:
  python3 tests/run_eval.py                 # corre todos los casos (hace llamadas a OpenAI)
  python3 tests/run_eval.py --list          # solo lista los casos, SIN llamar a OpenAI (gratis)
  python3 tests/run_eval.py --category kb_gap
  python3 tests/run_eval.py --id gap-ahorro-infantil-min
  python3 tests/run_eval.py --verbose       # imprime la respuesta completa de cada caso

Salida: exit code 0 si todos pasan, 1 si alguno falla (sirve para CI).
"""
import argparse
import json
import os
import sys
import unicodedata

CASES_FILE = os.path.join(os.path.dirname(__file__), "eval_cases.json")


def normalize(text: str) -> str:
    """Minúsculas y sin tildes, para comparar de forma robusta."""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def contains(haystack_norm: str, needle: str) -> bool:
    return normalize(needle) in haystack_norm


def evaluate(case: dict, answer: str, fallback_markers: list) -> list:
    """Devuelve la lista de motivos de falla. Lista vacía = caso aprobado."""
    failures = []
    ans = normalize(answer)

    for needle in case.get("must_contain", []):
        if not contains(ans, needle):
            failures.append(f"falta el texto esperado: '{needle}'")

    for needle in case.get("must_not_contain", []):
        if contains(ans, needle):
            failures.append(f"apareció texto prohibido: '{needle}'")

    if case.get("expect_fallback"):
        if not any(contains(ans, m) for m in fallback_markers):
            failures.append(
                "se esperaba la derivación (regla 3.1) y la respuesta no la contiene"
            )

    return failures


def main():
    parser = argparse.ArgumentParser(description="Evaluador del chatbot Nazareth")
    parser.add_argument("--list", action="store_true",
                        help="solo listar los casos, sin llamar a OpenAI")
    parser.add_argument("--category", help="filtrar por categoría (positive, retrieval, kb_gap)")
    parser.add_argument("--id", help="correr un único caso por su id")
    parser.add_argument("--verbose", action="store_true",
                        help="imprimir la respuesta completa de cada caso")
    args = parser.parse_args()

    with open(CASES_FILE, encoding="utf-8") as f:
        data = json.load(f)

    fallback_markers = data["fallback_markers"]
    cases = data["cases"]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.id:
        cases = [c for c in cases if c["id"] == args.id]

    if not cases:
        print("No hay casos que coincidan con el filtro.")
        return 1

    if args.list:
        print(f"{len(cases)} casos:\n")
        for c in cases:
            tag = "FALLBACK" if c.get("expect_fallback") else c["category"].upper()
            print(f"  [{tag:9}] {c['id']}: {c['question']}")
        return 0

    # Importar la cadena solo cuando vamos a usarla (evita exigir OPENAI_API_KEY para --list)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from src.agent_test.rag_chain import build_rag_chain

    print("Construyendo la cadena RAG (puede tardar la primera vez)...\n")
    qa_chain, context = build_rag_chain()

    passed, failed = 0, 0
    failed_cases = []

    for c in cases:
        try:
            response = qa_chain.invoke({
                "query": c["question"],
                "instructions": context,
                "conversation_history": [],
            })
            answer = str(response)
        except Exception as e:  # noqa: BLE001
            failed += 1
            failed_cases.append((c, [f"ERROR al invocar la cadena: {e}"]))
            print(f"✗ ERROR  {c['id']}: {e}")
            continue

        failures = evaluate(c, answer, fallback_markers)
        if failures:
            failed += 1
            failed_cases.append((c, failures))
            print(f"✗ FALLA  [{c['category']}] {c['id']}")
            print(f"    P: {c['question']}")
            for reason in failures:
                print(f"    → {reason}")
            print(f"    R: {answer.strip()[:300]}")
        else:
            passed += 1
            print(f"✓ OK     [{c['category']}] {c['id']}")

        if args.verbose:
            print(f"    Respuesta completa:\n    {answer.strip()}\n")

    total = passed + failed
    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{total} aprobados, {failed} fallidos")
    if failed_cases:
        print("\nCasos fallidos:")
        for c, reasons in failed_cases:
            print(f"  - {c['id']} ({c['category']}): {'; '.join(reasons)}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
