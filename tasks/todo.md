# Plan: Implementación del Agente YouTube Comments Collector

- [ ] 1. Actualizar las instrucciones del agente en `marketing_campaign_agent/instructions.py`:
  - [ ] Definir `YOUTUBE_COMMENTS_COLLECTOR_INSTRUCTION` con el prompt e instrucciones exactas proporcionadas por el usuario.
  - [ ] Especificar la regla de bypass si `total comments <= 100`.
  - [ ] Especificar el ordenamiento por más reciente (`sort by newest / most recent`).
  - [ ] Especificar el filtro de antigüedad (`<= 3 meses` / `from 3 months ago to the most current comment`).
  - [ ] Especificar el esquema JSON de salida exacto con `video_href`, `video_keywords` y `3_months_comments` (`Author`, `Msg`, `Reply`).

- [ ] 2. Actualizar y enriquecer la herramienta en `marketing_campaign_agent/tools/youtube_comment_extractor_tool.py`:
  - [ ] Soportar extracción y preservación de `video_keywords` desde la entrada.
  - [ ] Implementar verificación de umbral de comentarios (`total comments > 100`):
    - [ ] Vía YouTube Data API v3: consultar `videos.list(part="statistics")` para verificar `commentCount > 100`. Si `commentCount <= 100`, omitir / bypass.
    - [ ] Vía Playwright scraper fallback: verificar conteo en el encabezado de comentarios. Si `<= 100`, omitir / bypass.
  - [ ] Configurar filtro temporal a 3 meses por defecto (`max_months=3`).
  - [ ] Configurar ordenamiento por más recientes (`order="time"` / newest first).
  - [ ] Mapear la salida al formato requerido:
    - [ ] `video_href`: string
    - [ ] `video_keywords`: string
    - [ ] `3_months_comments`: lista de `{"Author": str, "Msg": str, "Reply": list}`.
  - [ ] Extraer respuestas (`Reply`) tanto en API v3 (`snippet.replies` / `commentThreads`) como en Playwright scraper.

- [ ] 3. Actualizar la configuración del agente en `marketing_campaign_agent/agent.py`:
  - [ ] Configurar `youtube_comments_collector_agent` (o alias) con la nueva instrucción y herramientas.
  - [ ] Asegurar la integración fluida en `campaign_orchestrator` (`SequentialAgent`).

- [ ] 4. Actualizar y ampliar la suite de pruebas en `tests/`:
  - [ ] Pruebas unitarias para filtrado de umbral `<= 100` (bypassed) vs `> 100` (extraído).
  - [ ] Pruebas de filtrado temporal de 3 meses (`3_months_comments`).
  - [ ] Pruebas de preservación de `video_keywords` y estructura `Author`, `Msg`, `Reply`.
  - [ ] Pruebas de integración con `AgentLoader` y `ADK Web`.

- [ ] 5. Ejecutar suite de pruebas con `pytest` y validar resultados.
- [ ] 6. Documentar lecciones en `tasks/lessons.md` y generar `walkthrough.md`.
