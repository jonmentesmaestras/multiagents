# Corrección de la investigación de landing pages

La causa registrada era el uso de Playwright Sync dentro del event loop de ADK.
El modelo recibía un error en lugar de la página y aun así generaba un análisis.

## Flujo actual

1. `GroundedLandingPageAgent` limpia los resultados de la investigación anterior.
2. Extrae la única URL HTTP/HTTPS del mensaje actual y ejecuta el scraper asíncrono.
3. Guarda el contenido, URL solicitada, URL final, idioma y estado HTTP en
   `landing_page_source`. Los errores de navegación, bloqueos reconocidos y
   extracciones con menos de 20 palabras detienen la investigación.
4. El modelo recibe únicamente la extracción actual, sin historial de otras ofertas.
5. Antes de publicar o guardar el análisis, Python comprueba el JSON, las cantidades
   de deseos/problemas/búsquedas y las citas requeridas contra `main_content`.
6. El orquestador permite continuar únicamente con un análisis validado en la misma
   invocación. Cada invocación comienza nuevamente por la extracción, incluso si
   existía un punto de reanudación de una secuencia anterior.

El scraper usa `async_playwright`. En Windows, si ADK utiliza un SelectorEventLoop,
la extracción se ejecuta en un hilo con su propio ProactorEventLoop para admitir
los subprocesos del navegador. El navegador se cierra también ante errores.

## Contrato de salida

Se conservan `source_info`, `avatar`, `main_promise`, `deseos`, `problemas` y
`youtube_keywords`. Se añaden `offer` y `evidence`. Los datos demográficos no
respaldados son `null`; el idioma de la página y el de las búsquedas se registran
por separado. La respuesta validada permanece como JSON serializado en
`landing_page_research`, compatible con los agentes posteriores.

Las citas deben existir literalmente en el texto, permitiendo diferencias de
espaciado. Esa comprobación confirma su procedencia, pero no demuestra por sí
sola que toda inferencia esté semánticamente justificada. La pertinencia se apoya
en las instrucciones y se revisó también en la ejecución real guardada aquí.
Los títulos de biografía reconocidos se separan en `secondary_content`; esta
separación y la detección de páginas de bloqueo son heurísticas.

## Reproducción

Reiniciar el proceso de ADK después de actualizar el código. Desde la raíz del
repositorio (`marketing-agents-adk`), ejecutar:

```powershell
.\.venv\Scripts\python.exe -m pytest tests marketing_campaign_agent\tests -q -p no:cacheprovider
.\.venv\Scripts\python.exe marketing_campaign_agent\diagnostics\verify_landing.py https://www.musicofwisdom.com/100frequencies
```

La segunda orden utiliza Chromium y el modelo configurado en el proyecto.
Ejecuta únicamente la investigación de la landing mediante un Runner de ADK y
una sesión nueva en memoria; no lanza búsquedas de YouTube ni altera sesiones
existentes. Guarda:

- `landing_source.json`: contenido que recibió el modelo.
- `landing_analysis.json`: análisis final con citas e inferencias identificadas.
- `landing_status.json`: resultado e identificador de la invocación.

Las regresiones comprueban errores de extracción, contenido vacío, bloqueo HTTP,
cierre del navegador, compatibilidad con el loop de Windows, datos de sesiones
anteriores, rechazo de JSON/citas inválidos y ausencia de llamadas a los agentes
posteriores cuando la investigación falla.
