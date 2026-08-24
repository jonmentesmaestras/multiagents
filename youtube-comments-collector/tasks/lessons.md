# Lecciones Aprendidas (tasks/lessons.md)

Este documento registra los patrones de errores detectados, las causas raíz y las reglas internas para evitar su repetición.

## Registro de Lecciones

- **Lección 1: Parámetro ArtifactMetadata en write_to_file**
  - *Contexto*: `write_to_file` con `ArtifactMetadata` solo debe usarse para rutas dentro de la carpeta de artifacts en brain (`<appDataDir>/brain/<conversation-id>`). Para archivos normales del proyecto / workspace, se debe omitir `ArtifactMetadata`.
  - *Regla*: Solo incluir `ArtifactMetadata` cuando el archivo objetivo esté en `<appDataDir>\brain\<conversation-id>`.

- **Lección 2: Selectores de YouTube dinámicos y Consent Popups**
  - *Contexto*: YouTube varía selectores ligeramente entre versiones A/B testing (ej. `span.ytAttributedStringHost` vs `#content-text`, `<ytd-menu-service-item-renderer>` vs `<div class="item style-scope yt-dropdown-menu">`).
  - *Regla*: Implementar selectores con listas de fallback ordenadas por prioridad (respetando los selectores explícitos solicitados por el usuario como primera prioridad) y manejar diálogos de cookies / consentimiento iniciales en diferentes idiomas.
