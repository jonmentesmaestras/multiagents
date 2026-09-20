# Lecciones Aprendidas (Lessons Learned)

## 1. Unificación de variables de entorno con `find_dotenv()`
- **Patrón:** En proyectos multi-agente con carpetas anidadas, tener múltiples archivos `.env` dispersos genera discrepancias y problemas de sincronización de claves.
- **Solución Elegante:** Mantener un único archivo `.env` en la raíz del proyecto y usar `load_dotenv(find_dotenv())` en los módulos. `find_dotenv()` asciende por el árbol de directorios automáticamente hasta encontrar el `.env` raíz, garantizando que el código funcione idénticamente ya sea ejecutado desde la raíz, una subcarpeta o mediante herramientas de CLI de ADK.

## 2. Precedencia de variables de autenticación en Google GenAI SDK
- **Patrón:** `google-genai` detecta tanto `GOOGLE_API_KEY` como `GEMINI_API_KEY`.
- **Regla:** Mantener ambas variables sincronizadas con el valor activo en el `.env` raíz para evitar discrepancias cuando diferentes librerías o submódulos soliciten una u otra variable.

## 3. Normalización idempotente de URLs canónicas de YouTube
- **Patrón:** Cuando se reciben URLs en múltiples formatos (links completos, enlaces cortos `youtu.be`, IDs individuales o embebidos), extraer el ID y reconstruir la URL sin verificar si ya es canónica puede provocar prefijos duplicados (ej: `https://www.youtube.com/watch?v=https://...`).
- **Solución Elegante:** Implementar una función helper centralizada (`_normalize_youtube_url`) que extraiga el ID limpio y genere la URL canónica `https://www.youtube.com/watch?v={id}` de forma idempotente.

## 4. Deserialización resiliente de texto raspado de la web (User-Generated Content)
- **Patrón:** Los comentarios extraídos de plataformas web pueden contener caracteres de control sin escapar, saltos de línea crudos o comillas HTML sin procesar, provocando errores en `json.loads`.
- **Solución Elegante:** Utilizar `strict=False` en las funciones de deserialización (`json.loads(..., strict=False)`) y construir helpers flexibles que procesen tanto listas de diccionarios, strings JSON, o estructuras intermedias anidadas sin interrumpir el pipeline multi-agente.

## 5. Anclaje Estricto (*Strict Grounding*) y Prevención de Alucinaciones por Dominio
- **Patrón:** Cuando un LLM analiza una URL o dominio conocido, la memoria paramétrica pre-entrenada puede sobreescribir el contenido real de la página. Por ejemplo, al raspar `musicofwisdom.com/100frequencies` (un lead magnet de bienestar holístico personal), el modelo alucinó licencias de música comercial porque la empresa matriz vende pistas libres de regalías en su catálogo general.
- **Solución Elegante:** Integrar directivas explícitas de *Strict Grounding* en las instrucciones del agente (`LANDING_PAGE_COPYWRITER_INSTRUCTION`):
  1. Forzar al modelo a basar su análisis **únicamente** en el texto extraído por la herramienta.
  2. Prohibir expresamente la extrapolación basada en el nombre del dominio o la empresa.
  3. Diferenciar claramente la **oferta principal de la página** (lead magnet, producto) frente a la biografía del instructor o enlaces secundarios del footer.
  4. Definir el avatar del cliente como el **consumidor final de esa oferta concreta**, no el perfil profesional del autor.

## 6. Exclusión de binarios de sesión (.adk/*.db) y variantes de .env (.env*)
- **Patrón:** Las bases de datos SQLite locales (`session.db`) pueden superar el límite de tamaño de GitHub (>100MB) y provocar fallos de codificación UTF-8 en herramientas de IA. Asimismo, copias locales accidentales (ej. `.env copy`) pueden filtrar claves de API si `.gitignore` solo especifica `.env`.
- **Solución Elegante:** Configurar `.gitignore` con `.env*` y excluir directorios de persistencia local como `.adk/`, `*.db`, `*.sqlite`, evitando que archivos pesados o sensibles ingresen al historial de Git.

## 7. Exclusión de archivos JSON de revisión humana (*revision_humana*.json y **/revision_humana/**/*.json)
- **Patrón:** Los volcados de diagnósticos y revisiones humanas generan múltiples archivos JSON por sesión en `docs/revision_humana/<session_id>/` o con nombres que incluyen `revision_humana`. Subirlos a Git genera ruido masivo en los commits y posible fuga de datasets voluminosos generados dinámicamente.
- **Solución Elegante:** Incluir reglas en `.gitignore` tanto para el patrón de nombre `*revision_humana*.json` como para subrutas anidadas `**/revision_humana/**/*.json`, asegurando además desindexar con `git rm --cached` cualquier archivo JSON histórico preexistente para que las reglas de exclusión tengan efecto inmediato sin borrar los archivos locales.

