# Plan: Implementación de Sub-agente 2 - YouTube Comments / Video Analyzer Agent

- [x] 1. Diseñar e implementar herramienta Playwright de búsqueda en YouTube (`marketing_campaign_agent/tools/youtube_search_tool.py`)
  - [x] Soporte para consulta con palabras clave codificadas/decodificadas
  - [x] Interacción con botón de filtros y ordenamiento por popularidad ("Popularity" / "Recuento de visualizaciones")
  - [x] Extracción de título, URL (`video_href`) y conteo de visualizaciones (`video_views`)
  - [x] Descarte de videos con menos de 100,000 views (< 100K)
  - [x] Manejo resiliente de cookies y selectores de YouTube
- [x] 2. Exportar la herramienta en `marketing_campaign_agent/tools/__init__.py`
- [x] 3. Refinar y estructurar las instrucciones en `marketing_campaign_agent/instructions.py` (`YOUTUBE_COMMENTS_ANALYZER_INSTRUCTION`)
- [x] 4. Configurar el sub-agente `youtube_comments_analyzer_agent` en `marketing_campaign_agent/agent.py` y agregarlo como segundo agente en el pipeline secuencial `campaign_orchestrator`
- [x] 5. Crear pruebas unitarias y de integración en `tests/test_youtube_analyzer.py` y actualizar `tests/test_agent.py`
- [x] 6. Ejecutar suite de pruebas pytest y validar compatibilidad con Google ADK (25/25 pruebas aprobadas)
- [x] 7. Documentar resultados y lecciones aprendidas

---

## Revisión Final

- **Herramienta Playwright (`search_youtube_videos`)**: Implementada con parseo bilingüe de conteo de vistas (`parse_view_count`), ordenamiento por popularidad directo y por UI, y descarte de videos < 100K vistas.
- **Sub-agente 2 (`youtube_comments_analyzer_agent`)**: Creado como `LlmAgent` con `name="YoutubeCommentsAnalyzer"`, `output_key="youtube_videos_research"`, y registrado en `campaign_orchestrator.sub_agents`.
- **Validación Completa**: 25/25 pruebas pasando en `pytest` y prueba en vivo de scraping ejecutada exitosamente.
