# Plan: Implementación de la Evaluación y Decisión del Orquestador

- [x] 1. Crear herramienta de evaluación cuantitativa `marketing_campaign_agent/tools/comments_evaluator_tool.py`:
  - [x] Implementar `evaluate_classified_comments_metrics(classified_comments)`:
    - [x] Contar comentarios clasificados como `deseo` (`deseos_count`).
    - [x] Contar comentarios clasificados como `problema` (`problemas_count`).
    - [x] Calcular la suma total (`total_classified = deseos_count + problemas_count`).
    - [x] Evaluar condiciones: `deseos_count > 50`, `problemas_count > 50`, o `total_classified >= 100`.
    - [x] Determinar la decisión (`ACCEPT_OFFER` vs `DO_NOT_ACCEPT_OFFER`) y la recomendación estratégica para el clon en español.
  - [x] Exportar la nueva herramienta en `marketing_campaign_agent/tools/__init__.py`.

- [x] 2. Actualizar las instrucciones del orquestador y del reporte final en `marketing_campaign_agent/instructions.py`:
  - [x] Definir `MARKET_RESEARCH_REPORT_INSTRUCTION` / `CAMPAIGN_REPORT_INSTRUCTION`:
    - [x] Evaluación de las preguntas del árbol de decisión: ¿Más de 50 en deseos? ¿Más de 50 en problemas? ¿Suma >= 100?
    - [x] Si no se cumplen los umbrales: concluir que el problema/deseo de la landing page de Brasil no tiene suficiente audiencia en YouTube en español y recomendar investigar más a fondo sin clonar aún.
    - [x] Si la suma alcanza 100 o más (o >50 en alguna categoría): concluir que existe tracción suficiente y recomendar continuar con la siguiente fase de investigación.
  - [x] Actualizar `CAMPAIGN_ORCHESTRATOR_INSTRUCTION` con el flujo completo de 5 pasos.

- [x] 3. Configurar el sub-agente de reporte y actualizar la orquestación en `marketing_campaign_agent/agent.py`:
  - [x] Crear `market_research_report_agent = LlmAgent(...)` con nombre `MarketResearchReportAgent`, `instruction=MARKET_RESEARCH_REPORT_INSTRUCTION`, `output_key="market_research_report"` y herramienta `evaluate_classified_comments_metrics`.
  - [x] Integrar `market_research_report_agent` como el 5to y último sub-agente en `campaign_orchestrator` (`SequentialAgent`).
  - [x] Exportar en `marketing_campaign_agent/__init__.py`.

- [x] 4. Crear suite de pruebas unitarias y de integración:
  - [x] Crear `tests/test_campaign_report.py` para validar la lógica de conteo, evaluación de umbrales (>50 deseos, >50 problemas, >=100 suma) y generación de dictámenes.
  - [x] Actualizar `tests/test_agent.py`, `tests/test_youtube_analyzer.py`, `tests/test_youtube_comment_extractor.py` y `tests/test_youtube_comments_classifier.py` para validar la secuencia completa de 5 sub-agentes.

- [x] 5. Ejecutar la suite completa con `pytest` y verificar que el 100% de las pruebas pasen (66/66 aprobadas).
- [x] 6. Documentar lecciones en `tasks/lessons.md` y generar `walkthrough.md`.

---

## Revisión Final

- **Evaluador Determinístico**: La herramienta `evaluate_classified_comments_metrics` realiza conteos matemáticos exactos sobre el dataset de comentarios clasificados, previniendo alucinaciones en el volumen de tracción.
- **Árbol de Decisión Completo**:
  - `deseos_count > 50` -> `ACCEPT_OFFER`
  - `problemas_count > 50` -> `ACCEPT_OFFER`
  - `deseos_count + problemas_count >= 100` -> `ACCEPT_OFFER` (Recomienda avanzar a la siguiente fase de investigación y desarrollo del clon).
  - Ninguna de las anteriores -> `DO_NOT_ACCEPT_OFFER` (Recomienda profundizar la investigación y NO proceder con el clon en español aún).
- **Orquestación de 5 Sub-Agentes**: La cadena de `SequentialAgent` coordina de principio a fin:
  1. `LandingPageResearcher`
  2. `YoutubeCommentsAnalyzer`
  3. `YoutubeCommentsCollector`
  4. `YoutubeCommentsClassifier`
  5. `MarketResearchReportAgent`
- **Suite de Pruebas**: 66 de 66 pruebas unitarias e integración aprobadas al 100% con `pytest`.

---

# Plan: Corrección de Inferencia y Anclaje Estricto de `landing_page_research_agent`

- [x] 1. Actualizar `LANDING_PAGE_COPYWRITER_INSTRUCTION` en `marketing_campaign_agent/instructions.py`:
  - [x] Implementar reglas explícitas de Anclaje Estricto (*Strict Grounding*): basar el análisis exclusivamente en el texto y la oferta concreta extraída por `scrape_landing_page`.
  - [x] Prohibir expresamente la extrapolación o suposición basada en el nombre de dominio o servicios externos del autor/empresa.
  - [x] Instruir al agente a identificar la oferta central ("lead magnet", curso, producto específico) distinguiéndola de la biografía del instructor o enlaces del footer.
  - [x] Definir el avatar del cliente ideal como el consumidor final que busca beneficiarse de la oferta específica.
  - [x] Mantener el esquema de salida JSON estricto (`source_info`, `avatar`, `main_promise`, `deseos`, `problemas`, `youtube_keywords`).
- [x] 2. Ajustar `marketing_campaign_agent/prompt_landing_page_research_agent.md` con las mismas directivas de anclaje estricto.
- [x] 3. Ejecutar suite de pruebas con `pytest` para asegurar que ningún test unitario o de integración se rompa (66/66 aprobadas).
- [x] 4. Validar la extracción con el scraper y verificar que los textos de frecuencias, bienestar y guía gratuita estén presentes en el payload.
- [x] 5. Actualizar `tasks/lessons.md` con la lección 5 sobre Strict Grounding y prevención de alucinaciones por dominio.
