# Recuperación automática

El clasificador conserva las decisiones válidas y distingue errores técnicos de ambigüedad semántica. Reintenta únicamente fallos técnicos en tres rondas de lotes de 10, 5 y 5 comentarios. Las esperas son progresivas y respetan Retry-After. Los errores permanentes de autenticación, permisos o petición detienen las llamadas. Cada lote recuperado se guarda antes de continuar.

La recolección recupera solo videos parciales, hasta tres rondas, fusionando los comentarios por identificador incluso cuando la nueva extracción sigue siendo parcial. Su estado se guarda después de cada video recuperado.

COMMENTS_RECOVERY_SECONDS configura el presupuesto de recuperación por etapa (600 segundos por defecto). No se inicia un nuevo lote después de vencer el presupuesto; una petición ya iniciada puede terminar dentro del timeout de su proveedor. COMMENTS_TARGET conserva el umbral de parada (100 por defecto).

COMMENTS_BATCH_TIMEOUT_SECONDS limita de extremo a extremo cada petición de clasificación (90 segundos por defecto). Al vencer, la petición asíncrona se cancela, el lote queda registrado como error técnico y entra en la recuperación acotada. La recolección guarda un checkpoint y muestra el total después de cada video, por lo que una reanudación procesa únicamente los videos que faltan. Una colección ya marcada como completa nunca se vuelve a extraer.

Los comentarios ambiguos se conservan para revisión humana. Al terminar se genera el informe y se exportan HTML y JSON bajo docs/revision_humana/<sesión>. El JSON incluye también los pendientes de revisión. Los archivos se regeneran al terminar otra ejecución de la misma sesión; guarda una copia antes de añadir anotaciones personales al JSON.

## Arranque con recuperación tras reinicios

Desde C:\Users\LENOVO\Desktop\marketing-agents-adk, con el servidor anterior detenido:

```powershell
.\.venv\Scripts\python.exe -m marketing_campaign_agent.recovery_server
```

Este lanzador conserva la interfaz ADK Web en http://127.0.0.1:8000 y la base de sesiones de la aplicación. En el arranque busca ejecuciones marcadas como activas que ya tengan comentarios guardados y las continúa. Usa PORT para cambiar el puerto.

La recuperación dentro de una ejecución también funciona con `adk web`; el lanzador anterior es necesario para recuperar automáticamente después de reiniciar el servidor. No inicia ni modifica servicios instalados en Windows.

El bloqueo por sesión impide dos ejecuciones concurrentes, incluso desde procesos distintos. Una cancelación recibida del usuario queda marcada como cancelled y no se reanuda en el siguiente arranque. Un cierre abrupto del proceso deja active y permite recuperar. Se permiten tres reinicios automáticos; después se informa el agotamiento. Las sesiones históricas sin pipeline_run, las finalizadas y las canceladas no se reabren.

## Estado auditable

- pipeline_run: estado de ejecución, etapa, invocación y reinicios.
- youtube_comments_recovery: huella de los datos/categorías/modelo, ronda, plazo, identificadores pendientes, próxima espera y motivo de cierre.
- youtube_collection_recovery: videos pendientes, ronda y plazo.
- failure_kind y attempts: causa estructurada e intentos de clasificación por comentario.
- human_review_files: rutas de los archivos exportados.

No se reintenta automáticamente la ambigüedad semántica. Alcanzar el umbral automático no sustituye la inspección humana de los comentarios que sustentan el resultado.
