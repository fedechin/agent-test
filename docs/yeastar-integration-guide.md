# Guía de Integración: Yeastar P560 + Agente IA WhatsApp

## Resumen

Esta guía describe los pasos para conectar su sistema Yeastar P560 (con WhatsApp ya configurado) al agente de inteligencia artificial. El agente IA responderá automáticamente los mensajes de WhatsApp, y cuando sea necesario, transferirá la conversación a un agente humano.

### Flujo de la Integración

```
Cliente envía WhatsApp → Yeastar P560 → Agente IA → Respuesta automática
                                              ↓
                              (Si se requiere) → Transferencia a agente humano
```

### Beneficios

- Respuesta inmediata 24/7 a consultas frecuentes
- Reducción de carga de trabajo para agentes humanos
- Escalamiento inteligente cuando se requiere atención personalizada
- Historial completo de conversaciones

---

## Requisitos

| Requisito | Detalle | Cómo verificar |
|-----------|---------|----------------|
| **Firmware** | Versión 37.20.0.128 o superior | Mantenimiento → Actualización |
| **Plan** | Enterprise Plan o Ultimate Plan | Información del sistema |
| **WhatsApp** | Canal de WhatsApp Business ya configurado y funcionando | Centro de Contacto → Canales |
| **Acceso remoto** | El PBX debe ser accesible desde internet (ver nota abajo) | Verificar acceso FQDN |

> **Tiempo estimado de configuración: 10-15 minutos**
>
> **Reversión: 30 segundos** (cambiar destino de vuelta a su configuración actual)

### Importante: Acceso al PBX desde Internet

Para que el agente IA pueda enviar respuestas y transferir conversaciones, nuestro servidor necesita comunicarse con la API del PBX. Esto requiere que el PBX sea accesible desde internet.

**Opción recomendada:** Si ya tienen configurado el **Acceso Remoto (FQDN)** de Yeastar (dirección tipo `xxx.ras.yeastar.com`), no necesitan hacer nada adicional. Simplemente proporcionen esa dirección como la URL del PBX.

**Si el PBX solo es accesible desde la red local:** Necesitarán habilitar una de estas opciones:
- **Acceso Remoto Yeastar (DDNS/FQDN):** Habilitarlo desde el panel del PBX en **Sistema → Red → Acceso Remoto**. Es la opción más sencilla y segura.
- **Port forwarding:** Abrir el puerto de la API (generalmente 8088) en su firewall/router hacia el PBX. Podemos proporcionar la IP fija de nuestro servidor para que solo permitan conexiones desde esa dirección.

---

## Paso 1: Habilitar API (si no está habilitada)

1. Ir a **Integraciones → API**
2. Verificar que esté activada la opción **"Habilitar API"**
3. Si no está habilitada, activarla
4. Anotar las credenciales:

```
Client ID: _________________________
Client Secret: _________________________
```

---

## Paso 2: Configurar Webhook

1. Ir a **Integraciones → API → Webhook**
2. Configurar:

| Campo | Valor |
|-------|-------|
| URL del Webhook | `https://[URL-DEL-AGENTE-IA]/yeastar/webhook` |
| Método | POST |

3. **Suscribirse a eventos**:
   - ✅ (30031) New Message Notification
   - ✅ (30032) Message Sending Result

4. Guardar y usar el botón **"Probar Webhook"** para verificar conectividad

---

## Paso 3: Modificar Destino del Canal WhatsApp

Este es el único cambio que afecta el flujo actual de mensajes.

1. Ir a **Centro de Contacto → Canales de Mensajería → WhatsApp**
2. Seleccionar el canal existente
3. Buscar **"Destino para Mensajes Entrantes"**

**Antes de cambiar, anote su configuración actual (para poder revertir):**

```
Destino actual: _________________________
(Cola, Extensión, u otro)
```

**Nueva configuración:**

```
Destino: Plataforma de Terceros (Third-Party Platform)
```

4. Guardar los cambios

---

## Paso 4: Anotar ID de Cola/Extensión para Transferencias

Para que el agente IA pueda transferir conversaciones a humanos, necesitamos el ID de la cola o extensión donde actualmente reciben los mensajes:

```
ID de cola/extensión para transferencias: _________________________
```

---

## Verificación

### Prueba 1: Conectividad del Webhook

- [ ] Webhook responde código 200 desde el botón de prueba de Yeastar
- [ ] Logs del agente IA muestran recepción del evento de prueba

### Prueba 2: Mensaje de Prueba

- [ ] Enviar mensaje de WhatsApp al número configurado
- [ ] Agente IA recibe el mensaje (verificar en logs)
- [ ] Agente IA responde correctamente
- [ ] Respuesta llega al WhatsApp del cliente

### Prueba 3: Transferencia a Humano

- [ ] Enviar mensaje solicitando hablar con un humano
- [ ] Agente IA detecta la solicitud
- [ ] Conversación aparece en la cola de agentes humanos
- [ ] Agente humano puede continuar la conversación

---

## Procedimiento de Reversión

Si la integración presenta problemas, se puede revertir en 30 segundos:

1. Ir a **Centro de Contacto → Canales de Mensajería → WhatsApp**
2. Cambiar **"Destino para Mensajes Entrantes"** de vuelta a la cola o extensión que tenían antes (la que anotó en el Paso 3)
3. Guardar

**Los mensajes volverán a llegar directamente a los agentes humanos como antes.**

Si además desean desactivar completamente la integración:
1. Ir a **Integraciones → API → Webhook**
2. Eliminar la configuración del webhook

---

## Preguntas Frecuentes

**¿Qué pasa si el agente IA no está disponible?**
Si el webhook no responde, Yeastar reintentará según su configuración. Se puede configurar un timeout para derivar automáticamente a humanos.

**¿Se pierden mensajes durante la transferencia?**
No. El historial completo de la conversación se mantiene.

**¿Los agentes humanos trabajan diferente?**
No. Siguen usando Linkus o el panel web como siempre. Solo que ahora reciben conversaciones pre-filtradas por la IA.

**¿Qué horario tiene el agente IA?**
El agente IA está disponible 24/7. Las transferencias a humanos dependen de la disponibilidad de la cola configurada.

**¿Podemos volver atrás?**
Sí, en 30 segundos. Solo cambien el destino del canal WhatsApp de vuelta a la cola/extensión anterior.

---

## Checklist de Información a Proporcionar

Antes de comenzar, por favor complete y envíe lo siguiente:

```
=== CREDENCIALES DE API ===
URL del PBX: https://________________________________
(Si tienen FQDN remoto, usar esa dirección. Ej: https://miempresa.ras.yeastar.com:8088)
Tipo de acceso: [ ] FQDN remoto (xxx.ras.yeastar.com)  [ ] IP local (requiere port forwarding)
Client ID: ________________________________
Client Secret: ________________________________

=== CONFIGURACIÓN EXISTENTE ===
Nombre del canal WhatsApp: ________________________________
Destino actual de mensajes: ________________________________
ID de cola para transferencias: ________________________________

=== CONTACTO TÉCNICO ===
Nombre: ________________________________
Email: ________________________________
Teléfono: ________________________________
```
