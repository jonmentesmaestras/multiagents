# Consolidación a un Único Archivo .env en la Raíz

- [x] Modificar `marketing_campaign_agent/agent.py` y `testApikey.py` para usar `find_dotenv()` y localizar automáticamente el `.env` raíz desde cualquier directorio
- [x] Eliminar el archivo redundante `marketing_campaign_agent/.env`
- [x] Validar la ejecución de `testApikey.py` desde la raíz y desde la subcarpeta
- [x] Ejecutar el suite completo de pruebas (`pytest`) para asegurar cero regresiones (8/8 pruebas pasadas)
- [x] Actualizar `tasks/lessons.md`
