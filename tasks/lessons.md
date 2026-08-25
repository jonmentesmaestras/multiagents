# Lecciones Aprendidas (Lessons Learned)

## 1. Unificación de variables de entorno con `find_dotenv()`
- **Patrón:** En proyectos multi-agente con carpetas anidadas, tener múltiples archivos `.env` dispersos genera discrepancias y problemas de sincronización de claves.
- **Solución Elegante:** Mantener un único archivo `.env` en la raíz del proyecto y usar `load_dotenv(find_dotenv())` en los módulos. `find_dotenv()` asciende por el árbol de directorios automáticamente hasta encontrar el `.env` raíz, garantizando que el código funcione idénticamente ya sea ejecutado desde la raíz, una subcarpeta o mediante herramientas de CLI de ADK.

## 2. Precedencia de variables de autenticación en Google GenAI SDK
- **Patrón:** `google-genai` detecta tanto `GOOGLE_API_KEY` como `GEMINI_API_KEY`.
- **Regla:** Mantener ambas variables sincronizadas con el valor activo en el `.env` raíz para evitar discrepancias cuando diferentes librerías o submódulos soliciten una u otra variable.
