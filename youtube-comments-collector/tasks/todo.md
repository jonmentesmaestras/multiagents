# YouTube Comments Collector - Refactor: Filtrado de Comentarios por Fecha (<= 6 meses)

## Requisitos y Especificaciones del Refactor
- **Nuevo Criterio de Filtrado**:
  - Extraer el texto de tiempo relativo del tag `<a>` dentro de `<span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model"> <a class="yt-simple-endpoint style-scope ytd-comment-view-model" href="...">6 months ago</a> </span>`.
  - Solo recolectar comentarios publicados desde hace 6 meses hasta la fecha más reciente (<= 6 meses).
  - Descartar/filtrar comentarios publicados hace 7 meses o más antiguos (>= 7 meses, años).
  - Optimización: Cuando los comentarios están ordenados por más recientes ("Newest first"), si se detectan comentarios de >= 7 meses consecutivos, detener la paginación/scroll de forma temprana.
  - Parametrización: Permitir configurar `max_months: Optional[int] = 6` vía CLI (`--max-months 6`) y vía Python API.

## Tareas

- [x] 1. Crear parser de tiempo relativo en `youtube_scraper/parser.py` (`parse_relative_time_months`, `is_within_time_limit`) con soporte para segundos, minutos, horas, días, semanas, meses, años y variantes multilenguaje ("(edited)", "hace X meses", etc.).
- [x] 2. Agregar selectores de fecha en `youtube_scraper/selectors.py` (`span#published-time-text a`, etc.).
- [x] 3. Refactorizar `youtube_scraper/scraper.py` para extraer la fecha de publicación, evaluar la condición <= 6 meses y filtrar comentarios antiguos, con early stopping en orden "newest".
- [x] 4. Actualizar `youtube_scraper/cli.py` con el argumento `--max-months` (default 6).
- [x] 5. Crear pruebas unitarias para el parser de tiempo en `tests/test_parser.py`.
- [x] 6. Actualizar pruebas en `tests/test_mock_scraper.py` y `tests/test_cli.py` con comentarios de diferentes antigüedades (ej. 2 days ago, 5 months ago, 6 months ago, 7 months ago, 1 year ago).
- [x] 7. Ejecutar suite de pruebas pytest completa (12/12 pruebas aprobadas).
- [x] 8. Actualizar documentación en `README.md`.
- [x] 9. Revisión final y lecciones aprendidas.

---

## Revisión Final

- **Lógica de Fecha**: Se implementó el filtrado preciso que evalúa la etiqueta `<a>` en `<span dir="auto" id="published-time-text" class="style-scope ytd-comment-view-model">`.
- **Condición Estricta**: Comentarios <= 6 meses (segundos, minutos, horas, días, semanas y hasta 6 meses) son aceptados; comentarios >= 7 meses (7 meses, 8 meses, 1 año, etc.) son descartados.
- **Suite de Pruebas**: 12/12 pruebas pasando exitosamente en pytest.
