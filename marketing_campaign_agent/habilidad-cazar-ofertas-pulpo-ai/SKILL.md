---
name: cazar-ofertas-pulpo-ai
description: Busca y evalúa ofertas ganadoras en Pulpo AI mediante filtros de nicho y checkout, carga resultados con scroll y devuelve tres oportunidades con diez días o más de actividad en JSON.
---

# Cazar ofertas en Pulpo AI

Usa esta habilidad cuando el usuario quiera investigar anuncios u ofertas en Pulpo AI para detectar productos digitales que puedan modelarse en otro mercado o idioma.

## Flujo de trabajo

1. Confirma el nicho, los checkouts y cualquier criterio adicional. Si el usuario ya los indicó, no los vuelvas a preguntar.
2. En Pulpo AI, abre **Cazar Presas**.
3. Configura los filtros solicitados. Para una búsqueda gastronómica de referencia, pueden usarse los checkouts Hotmart, Kiwify y Panda y el nicho Gastronomía.
4. Ejecuta la búsqueda.
5. Revisa las tarjetas y desplázate hacia abajo para activar la carga progresiva (lazy load). Continúa hasta que no aparezcan nuevas tarjetas o hasta que se haya revisado una cantidad razonable de resultados.
6. Conserva únicamente ofertas cuya tarjeta indique **diez días o más** de actividad. No confundas el número de anuncios con los días activos.
7. Abre los detalles de las candidatas para obtener el ID del anuncio y la landing exactos.
8. Escoge tres ofertas usando, en este orden, estos criterios: permanencia, claridad de la promesa, facilidad de crear un producto equivalente y variedad de ángulos publicitarios.
9. Entrega el resultado en JSON válido, sin comentarios fuera del JSON si el usuario pidió únicamente JSON.

## Formato de salida

```json
[
  {
    "id_anuncio": "...",
    "landing": "...",
    "dias_activo": 0,
    "por_que_se_escogio": "..."
  }
]
```

La justificación debe basarse en datos visibles de la tarjeta o de la landing: días activos, volumen de anuncios, promesa, formato del producto, bonos y facilidad de adaptación. Presenta las URLs completas como texto dentro del JSON.

## Reglas de precisión

- No inventes IDs, precios, días activos ni URLs.
- Si una landing no carga o no muestra el precio, indícalo claramente y no lo presentes como dato verificado.
- Si hay menos de tres ofertas que cumplen el mínimo de diez días, devuelve las disponibles y explica la limitación.
- "Oferta ganadora" es una hipótesis basada en señales como permanencia y volumen; no equivale a rentabilidad comprobada ni a Product-Market Fit.
- Para evaluar una prueba publicitaria, separa siempre gasto, ventas, ingresos, comisiones y margen. Siete ventas no confirman por sí solas Product-Market Fit.

## Adaptación a español

Después de seleccionar una oferta, resume cómo podría adaptarse al mercado hispano sin copiar afirmaciones engañosas, testimonios, identidad de expertos ni materiales protegidos. Propón nombres, precio de prueba y ángulos publicitarios como hipótesis que deben validarse.
