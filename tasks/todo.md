# Plan: Implementación del Agente YouTube Comments Classifier

- [ ] 1. Definir las instrucciones del agente en `marketing_campaign_agent/instructions.py`:
  - [ ] Crear `YOUTUBE_COMMENTS_CLASSIFIER_INSTRUCTION`.
  - [ ] Instruir el consumo de `deseos` y `problemas` desde `landing_page_research`.
  - [ ] Instruir el recorrido de `youtube_comments_collected` y cada comentario dentro de `3_months_comments` (`Msg`).
  - [ ] Definir la lógica de clasificación: primero evaluar contra `deseos` (categoría "deseo"); si no aplica, evaluar contra `problemas` (categoría "problema").
  - [ ] Definir la regla de exclusión para comentarios no relevantes (saludos, ruido, spam sin dolor/deseo).
  - [ ] Especificar el esquema JSON estricto de salida con `categoria`, `deseo`/`problema`, `Msg`, `razon`, `video_href`.

- [ ] 2. Configurar el agente en `marketing_campaign_agent/agent.py`:
  - [ ] Crear `youtube_comments_classifier_agent = LlmAgent(...)` con `name="YoutubeCommentsClassifier"` y `output_key="youtube_comments_classified"`.
  - [ ] Integrar el sub-agente como el 4to paso en `campaign_orchestrator` (`SequentialAgent`).
  - [ ] Exportar `youtube_comments_classifier_agent` en `marketing_campaign_agent/__init__.py`.

- [ ] 3. Actualizar y crear la suite de pruebas unitarias y de integración:
  - [ ] Crear `tests/test_youtube_comments_classifier.py` para validar la configuración del agente, prompt y estructura de salida esperada.
  - [ ] Actualizar `tests/test_agent.py` para verificar que `campaign_orchestrator` contiene los 4 sub-agentes en la secuencia correcta.

- [ ] 4. Ejecutar la suite de pruebas con `pytest` y validar que el 100% de las pruebas pasen.
- [ ] 5. Documentar lecciones en `tasks/lessons.md` y generar `walkthrough.md`.
