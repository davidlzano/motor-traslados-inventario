# Motor de optimización de traslados de inventario

![Architecture](docs/architecture.png)

Genera el plan diario de redistribución de inventario para una red de tiendas retail: qué mover, desde dónde, hacia dónde y en qué cantidad, respetando las restricciones logísticas y económicas de la operación.

Este repositorio es una **reimplementación demostrativa** de un sistema que diseñé y puse en producción para una cadena con cerca de 470 tiendas a nivel nacional, donde reemplazó un ejercicio manual sobre hojas de cálculo que tomaba una semana al mes. El código aquí publicado es original, usa datos sintéticos y no contiene información de la empresa.

---

## El problema

Una red de tiendas acumula dos desequilibrios en paralelo:

- Tiendas con **faltante**: producto que se vende pero no hay en el punto
- Tiendas con **exceso**: producto que sobra y no rota

Ambos cuestan dinero. El faltante es venta perdida; el exceso es capital inmovilizado. La solución obvia es mover mercancía de donde sobra a donde falta, pero mover cuesta: hay que pagar flete, y un envío de tres unidades a ochenta kilómetros cuesta más que la mercancía que traslada.

A esto se suman restricciones que hacen inviable la solución ingenua:

- No toda tienda puede recibir todo producto (una tienda de adulto no vende ropa infantil)
- Los outlets tienen capacidad finita de absorción, y varía según su rotación real
- El producto descontinuado tiene un destino distinto al producto activo
- Hay una distancia máxima operativamente razonable

## El enfoque

Es una variante del **problema de transporte**. La solución exacta por programación lineal es costosa de calcular a esta escala y, más importante, difícil de explicar a quien ejecuta los traslados en bodega.

Se resuelve con una **heurística voraz priorizada en tres etapas**, ordenadas por retorno económico por unidad movida:

### 1. Recuperación — Outlet → Tienda regular

Producto activo que quedó atrapado en un outlet, donde se liquida con descuento, devuelto a una tienda que lo necesita y puede venderlo a precio pleno. Es la etapa de mayor retorno: recupera margen que se estaba perdiendo.

### 2. Rebalanceo — Tienda regular → Tienda regular

Excedente por encima del máximo parametrizado movido hacia tiendas con faltante. No cambia el inventario total de la red, solo lo reubica donde puede venderse.

### 3. Evacuación — Tienda regular → Outlet

Producto descontinuado que ocupa metros cuadrados en tienda regular, enviado al canal de liquidación. Se reparte entre outlets según su capacidad disponible y con un tope por SKU, para no concentrar treinta unidades del mismo producto en un solo punto.

Cada etapa consume del estado que deja la anterior: una unidad asignada en la etapa 1 ya no está disponible para la 2. Eso garantiza que ninguna unidad se comprometa dos veces.

---

## Decisiones de diseño

**Distancia geodésica calculada, no tabla de distancias.** Se implementa la fórmula de Haversine sobre las coordenadas de cada ciudad. Mantener una matriz de distancias entre cientos de ciudades es un problema de mantenimiento; calcularla son seis líneas de trigonometría. Los resultados se cachean porque los mismos pares se consultan miles de veces por corrida.

**Dos regímenes de velocidad.** El tiempo de viaje no es lineal con la distancia: un trayecto urbano corto es mucho más lento por kilómetro que uno por carretera. Se usan 22 km/h bajo 45 km y 55 km/h por encima.

**Capacidad de outlet dinámica, no fija.** Asignar un tope igual a todos los outlets es un error costoso: llena de mercancía puntos que no rotan y desaprovecha los que sí. La capacidad se deriva de las ventas reales de los últimos 90 días, proyectadas a los días de cobertura permitidos, descontando el stock actual.

**Filtro económico por par origen-destino, no por línea.** Veinte líneas de una unidad entre las mismas dos tiendas sí llenan un bulto y justifican el flete, aunque cada línea aislada parezca insignificante. Filtrar línea por línea descartaría envíos perfectamente viables.

**Selección del origen más cercano.** Cuando varias tiendas pueden surtir un faltante, gana la más cercana. Es voraz y no garantiza el óptimo global, pero produce planes que un coordinador logístico entiende y puede auditar, que en la práctica vale más que un óptimo que nadie sabe explicar.

---

## Ejecución

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt

python generar_datos.py     # crea inventario.db con datos sintéticos
python motor_traslados.py   # genera plan_traslados.csv
```

Salida de ejemplo:

```
Cargando inventario...
  7820 filas de inventario en 120 tiendas
Generando plan...
Filtros: 665 -> 153 lineas (512 descartadas)

Plan exportado a plan_traslados.csv
Lineas:   153
Unidades: 546

Por prioridad:
                lineas  unidades
1-RECUPERACION      95       275
2-REBALANCEO         9        31
3-EVACUACION        49       240
```

Que se descarten 512 de 665 líneas es el comportamiento correcto: son traslados que el filtro económico considera inviables. Sin ese filtro, el plan mandaría a bodega a armar cientos de envíos que cuestan más de lo que mueven.

---

## Estructura

| Archivo | Contenido |
|---|---|
| `ciudades.py` | Coordenadas y cálculo de distancias geodésicas |
| `generar_datos.py` | Genera la red ficticia y el inventario en SQLite |
| `motor_traslados.py` | Carga, algoritmo de tres etapas, filtros y exportación |

---

## Parámetros ajustables

En `motor_traslados.py`:

| Parámetro | Valor | Efecto |
|---|---|---|
| `DIAS_COBERTURA_OUTLET` | 60 | Días de inventario que un outlet puede absorber |
| `MAX_UNIDADES_SKU_POR_OUTLET` | 5 | Tope por SKU para no saturar un punto |
| `MIN_UNIDADES_POR_ENVIO` | 10 | Piso de unidades por par origen-destino |
| `MAX_KM_TRASLADO` | 100 | Distancia máxima operativamente razonable |

Estos valores son de ejemplo. En una implementación real se calibran contra el costo de flete y los tiempos de la operación.

---

## Posibles extensiones

- Costo de flete explícito por tramo, en vez de la distancia como proxy
- Comparación contra una solución exacta por programación lineal en subconjuntos pequeños, para medir qué tan lejos queda la heurística del óptimo
- Consolidación de envíos por ruta, agrupando destinos sobre el mismo corredor

---

## Licencia

MIT
