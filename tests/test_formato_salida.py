#!/usr/bin/env python3
"""
Casos de strip_markdown_layout: el texto que sale hacia WhatsApp no debe llevar
markdown que WhatsApp no renderiza (bloques ```, títulos #, tablas |).

Es la red de seguridad del filtro de alcance: si un pedido de formato se le escapa
(pasó con "¿por qué no redactaste en formato markdown?"), igual sale texto plano.
No llama a OpenAI.

Uso:
  python3 tests/test_formato_salida.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "no-se-usa")
from src.agent_test.rag_chain import strip_markdown_layout  # noqa: E402

TABLA = """Disculpe la confusión. Aquí tiene los datos:

```markdown
# Subsidios de la Cooperativa

## Subsidios por Nacimiento
| Tipo de Subsidio | Antigüedad | Monto (Gs.) |
|------------------|-----------|-------------|
| Parto normal | 1 | 700.000 |
| Parto quirúrgico | 1 | 1.000.000 |
```
"""


def main():
    fallas = []
    salida = strip_markdown_layout(TABLA)
    for prohibido in ("```", "|", "#"):
        if prohibido in salida:
            fallas.append(f"quedó '{prohibido}' en la salida:\n{salida}")
    for esperado in ("*Subsidios de la Cooperativa*", "*Parto normal*",
                     "Monto (Gs.): 700.000", "Antigüedad: 1"):
        if esperado not in salida:
            fallas.append(f"falta '{esperado}' en la salida:\n{salida}")

    # Una respuesta normal no se toca: viñetas y negritas son el formato pedido.
    normal = ("Los tipos de ahorro son:\n\n- Caja de Ahorro a la Vista\n"
              "- Ahorro a Plazo Fijo\n\n¿Le gustaría conocer las condiciones? 😊")
    if strip_markdown_layout(normal) != normal:
        fallas.append(f"modificó una respuesta normal:\n{strip_markdown_layout(normal)}")

    # Tampoco toca montos ni texto con almohadilla suelta o barras dentro de la línea.
    otros = "El monto es Gs. 700.000 (Nº 3) y aplica a Mastología / Ginecología."
    if strip_markdown_layout(otros) != otros:
        fallas.append(f"modificó texto plano:\n{strip_markdown_layout(otros)}")

    # Tabla sin encabezado reconocible: igual sale como viñetas.
    suelta = "| Crédito Ordinario | 400.000.000 |"
    if "|" in strip_markdown_layout(suelta):
        fallas.append(f"no convirtió la fila suelta:\n{strip_markdown_layout(suelta)}")

    for f in fallas:
        print("✗", f)
    print(f"{4 - len(set(f.split(':')[0] for f in fallas))}/4 comprobaciones OK"
          if fallas else "4/4 comprobaciones OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
