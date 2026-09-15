#!/usr/bin/env python3
"""
Casos del detector de derivación implícita (rag_chain.detect_implicit_derivation).

No llama a OpenAI: son respuestas REALES del modelo, guardadas al medir el eval.
Las "derivaciones sin etiqueta" deben detectarse; las respuestas correctas, no.

Uso:
  python3 tests/test_derivacion_implicita.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OPENAI_API_KEY", "no-se-usa")
from src.agent_test.rag_chain import detect_implicit_derivation  # noqa: E402

# (respuesta del modelo, área esperada o None si NO es derivación)
CASOS = [
    # gap-rueda-de-ahorros: reconoce el hueco y remite, pero sin etiqueta.
    (
        "La Rueda de Ahorro es una modalidad de ahorro de la Cooperativa Multiactiva "
        "Nazareth. Sin embargo, el mecanismo de funcionamiento, los montos, los plazos y "
        "los tipos de Rueda NO figuran en esta base de conocimiento. Por lo tanto, no "
        "puedo brindarle detalles específicos sobre cómo funciona.\n\nSi desea más "
        "información, le recomiendo consultar directamente con un agente humano en "
        "cualquiera de nuestras sucursales o llamando al (021) 552631.",
        "GENERAL",
    ),
    (
        "La Rueda de Ahorro es una modalidad de ahorro de la Cooperativa Multiactiva "
        "Nazareth. Sin embargo, el mecanismo de funcionamiento, los montos, los plazos y "
        "los tipos de Rueda NO figuran en esta base de conocimiento. Por lo tanto, para "
        "obtener esa información específica, le recomiendo que se comunique directamente "
        "con la cooperativa.",
        "GENERAL",
    ),
    (
        "Los tipos de Rueda NO figuran en esta base de conocimiento. Por lo tanto, no "
        "puedo brindarle detalles específicos sobre cómo funciona.\n\nSi desea, puedo "
        "derivar su consulta a un agente humano para que le brinde más información. "
        "¿Le gustaría?",
        "GENERAL",
    ),
    # gap-salones-alquilar-country: remite a Educación sin etiqueta.
    (
        "La base de conocimiento no especifica si se puede alquilar el Country Club para "
        "eventos. Para consultas sobre alquileres y condiciones específicas del Country "
        "Club, le recomiendo contactar directamente con el Departamento de Educación o la "
        "administración correspondiente.",
        "EDUCACION",
    ),
    # Remite a los teléfonos del Centro Médico.
    (
        "No figuran los horarios de Traumatología. Puede llamar al 021 238 6777 int. "
        "1800 para consultarlos.",
        "CENTRO_MEDICO",
    ),
    # --- NO son derivaciones implícitas ---
    # pos-centro-medico-especialidades-cantidad: respuesta correcta que menciona un
    # faltante pero no remite a nadie. Derivar le borraría la lista al socio.
    (
        "El Centro Médico cuenta con las siguientes especialidades:\n- Clínica Médica\n"
        "- Pediatría\n- Urología\n\nEn total, son 12 especialidades listadas en la base "
        "de conocimiento. No figuran 20 especialidades. ¿Le gustaría que le ayude con "
        "información sobre alguna especialidad en particular?",
        None,
    ),
    # Ya trae etiqueta: la procesa main.py, no hay que tocarla.
    (
        "[DERIVAR_HUMANO:GENERAL] No tengo esa información, pero voy a derivar su consulta "
        "a un agente humano, que se pondrá en contacto con usted a la brevedad.",
        None,
    ),
    # Respuesta con dato y teléfono, sin falta de dato.
    (
        "Para reservar un turno en el Centro Médico puede llamar al 021 238 6777 int. 1800 "
        "o al 0981 770069.",
        None,
    ),
    # Remisión sin falta de dato (el procedimiento está en la base).
    (
        "Para desbloquear su tarjeta le recomiendo acercarse a cualquiera de nuestras "
        "sucursales en horario de atención.",
        None,
    ),
]


def main():
    fallas = 0
    for respuesta, esperado in CASOS:
        obtenido = detect_implicit_derivation(respuesta)
        if obtenido != esperado:
            fallas += 1
            print(f"✗ esperado={esperado} obtenido={obtenido}\n    {respuesta[:120]}")
    print(f"{len(CASOS) - fallas}/{len(CASOS)} casos correctos")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
