# Revisión pendiente de la Base de Conocimiento

Estas NO son fallas del chatbot, sino del **contenido** de la base de conocimiento
(`data/BC_Cooperativa_Nazareth_General.md` y `data/Subsidios_2026.md`). Cada punto
requiere que una persona verifique el dato contra la fuente oficial
(`data/source/`) y luego edite el `.md` correspondiente.

Mientras el dato no esté en la KB, lo correcto es que el bot responda con la frase
de derivación (regla 3.1) **al área que corresponda** (regla 3.1.1). Esos casos
están cubiertos como `kb_gap` en `tests/eval_cases.json`, con el área esperada en
el campo `expect_area`. Al cargar el dato real, mover el caso de `kb_gap` a
`positive` con el `must_contain` correspondiente.

---

## Estado tras el feedback del 07jul26

El cliente devolvió el Excel con **una sola columna nueva** (sin encabezado, la
columna L). Las columnas A–H las genera `generate_feedback_report.py` y las I–K
venían de la ronda de junio. Esas 15 notas se dividieron en dos grupos:

- **"Se agregó al archivo"** → datos cargados en la KB desde
  `Proyecto de implementación de chatbot.docx`.
- **"Se debe derivar a…"** → el cliente decidió NO publicar el dato y derivar a un
  área concreta. Implementado como áreas de derivación (ver más abajo).

### Cargado en la KB en esta ronda

- [x] **Centro Médico — número de reservas**: 021 238 6777 int. 1800 / 0981 770069.
- [x] **Centro Médico — lista de especialidades** (12).
- [x] **Country Club — días y horarios de ingreso** (temporada alta y baja).
- [x] **Country Club — camping**: se permite, consultando disponibilidad y costos.
- [x] **Rueda de Ahorro**: agregada al **listado** de tipos de ahorro. El detalle
      sigue siendo insuficiente (ver pendiente 1).

### Convertido en derivación por área (regla 3.1.1)

Ya no son huecos que haya que llenar: el cliente pidió expresamente derivar.

- [x] Centro Médico → **costos** de consultas/especialidades.
- [x] Centro Médico → **días y horarios** por especialidad.
- [x] Educación → **canon y cuota de la precooperativa** (se quitó Gs. 5.000 de la KB).
- [x] Educación → **extensión de horario** en el alquiler de salones.
- [x] General → **montos mínimos/máximos de los tipos de ahorro** (el cliente pidió
      derivar sin especificar área).

---

## Pendiente

## 1. Rueda de Ahorros — detalle insuficiente

El docx solo aporta: *"Esta modalidad de ahorro está sujeta a la disponibilidad de
cuentas de cada tipo de Rueda"*. Con eso el bot no puede responder **qué es** una
rueda de ahorros.

**Verificado en la evaluación:** con solo esa línea, el modelo inventaba el
mecanismo con conocimiento general (socios que se agrupan y aportan por turnos,
tipo "rueda"/ROSCA), que es exactamente lo que prohíbe la regla 4.3. Por eso la KB
ahora dice explícitamente que el mecanismo no figura y el caso quedó como `kb_gap`
(`gap-rueda-de-ahorros`), derivando a GENERAL.

- [ ] Pedir descripción, montos, plazos y requisitos, y qué son los "tipos de Rueda".
      Al cargarlo, pasar el caso a `positive`.

## 2. Centro Médico — "más de 20 especialidades" vs. 12 listadas

El docx mantiene el texto "con más de 20 especialidades" pero lista 12. Se cargaron
las 12 y **se quitó el número** para que el bot no se contradiga.

- [ ] Confirmar si faltan especialidades en la lista, o si el "más de 20" era incorrecto.

## 3. Country Club — alquiler para eventos

El cliente marcó *"Se agregaron los datos en el archivo"* (feedback #20), pero el
docx **no contiene nada** sobre alquilar el Country. Sigue siendo un hueco.

- [ ] Pedir condiciones de alquiler del Country, incluido el acceso de personas no
      socias sin acceso a la pileta.

## 4. Precooperativa — datos a verificar

- [ ] **Edad de ingreso**: la KB dice "Tener **6 años** cumplidos". En junio se marcó
      que podría ser en **meses**; el docx de julio sigue diciendo 6 años, así que el
      dato **no fue confirmado**. Verificar contra la fuente.
- [ ] **Beneficios**: la KB describe objetivo y requisitos, pero no lista "beneficios".
      Hoy deriva a Educación; si se quieren publicar, pedir la lista.

## 5. Centro Médico — nota ARA

- [ ] Agregar nota: para reservas y/o días disponibles el socio **debe consultar
      igualmente con ARA** (los profesionales a veces atienden en días extra).
      *(ARA = persona/área encargada de reservas — confirmar nombre/cargo exacto.)*

## 6. Créditos y subsidios — completitud

- [ ] Confirmar que estén **todos** los créditos especiales vigentes (Che Róga Porä
      ya está en la KB). Si hay más, agregarlos.
- [ ] Los 53 subsidios están en `data/Subsidios_2026.md`. Si el bot trae solo algunos,
      es problema de **recuperación**, no de contenido (cubierto por `ret-subsidios-listado`).

---

## Nota sobre el Departamento de Educación

Las derivaciones a Educación usan hoy el conmutador general **(021) 552631** porque
no tenemos un número directo del área.

- [ ] Pedir teléfono/interno directo del Departamento de Educación y actualizarlo en
      `DERIVATION_AREAS` (`src/agent_test/rag_chain.py`) y en la regla 3.1.1 de
      `context/context.txt`.
