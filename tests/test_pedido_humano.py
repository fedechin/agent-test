#!/usr/bin/env python3
"""
Casos de la detección de pedido explícito de humano
(ConversationManager.should_handover_to_human).

Ese pedido transfiere DE INMEDIATO, sin preguntar ni pasar por el bot, así que un
falso positivo corta la charla y ocupa a una persona. No llama a OpenAI.

Uso:
  python3 tests/test_pedido_humano.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.agent_test.conversation_manager import ConversationManager  # noqa: E402

PIDE_HUMANO = [
    "Quiero hablar con una persona",
    "quiero hablar con un humano",
    "¿Puedo hablar con alguien de créditos?",
    "Necesito hablar con un asesor",
    "pasame con un agente",
    "Podés pasarme con alguien por favor",
    "Transferime a un operador",
    "¿Me podés transferir con una persona?",
    "me comunicas con un asesor?",
    "Comunicame con alguien",
    "quiero un humano",
    "Necesito una persona real",
    "Agente humano",
    "necesito atención humana",
    "hablar con humano",
    "I want to talk to a human",
]

NO_PIDE_HUMANO = [
    # Reportado en producción: transfería directo.
    "Podes pasarme las especializaciones en formato json",
    "pasame el número 2",
    "¿Me puede pasar los requisitos del crédito ordinario?",
    "Pasame el número del centro médico",
    "¿El crédito es para una persona sola o puede ser conjunto?",
    "No entiendo cómo funciona la rueda de ahorro",
    "Necesito ayuda con mi crédito",
    "¿Cuál es el horario de atención al cliente?",
    "¿Puedo transferir dinero a una persona que no es socia?",
    "Esto no funciona, la app no me deja entrar",
    "¿Cuánto cuesta alquilar un salón para 100 personas?",
    "¿Puedo hablar con el centro médico por whatsapp?",
]


def main():
    cm = ConversationManager()
    fallas = 0
    for texto in PIDE_HUMANO:
        if not cm.should_handover_to_human(texto):
            fallas += 1
            print(f"✗ debía transferir: {texto}")
    for texto in NO_PIDE_HUMANO:
        if cm.should_handover_to_human(texto):
            fallas += 1
            print(f"✗ NO debía transferir: {texto}")
    total = len(PIDE_HUMANO) + len(NO_PIDE_HUMANO)
    print(f"{total - fallas}/{total} casos correctos")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
