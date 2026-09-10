"""
Motor de optimización de traslados de inventario.

Lee el inventario de una red de tiendas y genera un plan de redistribución
priorizado, respetando las restricciones operativas y económicas del negocio.

El problema es una variante del problema de transporte: hay puntos con
exceso, puntos con faltante, y un costo de mover unidades entre ellos. La
solución exacta por programación lineal es cara de calcular a esta escala y
difícil de explicar a quien ejecuta los traslados, así que se resuelve con
una heurística voraz priorizada en tres etapas.

Uso:
    python generar_datos.py     # crea la base de ejemplo
    python motor_traslados.py   # genera plan_traslados.csv
"""

import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

from ciudades import distancia_km, horas_viaje

RUTA_DB = Path("inventario.db")
RUTA_SALIDA = Path("plan_traslados.csv")

# --- Compatibilidad producto / tienda ---
COMPATIBILIDAD = {
    "HOMBRE": {"ADULTO", "MIXTA"},
    "MUJER": {"ADULTO", "MIXTA"},
    "ADULTO UNISEX": {"ADULTO", "MIXTA"},
    "NINO": {"INFANTIL", "MIXTA"},
    "NINA": {"INFANTIL", "MIXTA"},
    "BEBE": {"INFANTIL", "MIXTA"},
}

# --- Parámetros de capacidad de outlets ---
DIAS_COBERTURA_OUTLET = 60   # Días de inventario que un outlet puede absorber
CAPACIDAD_MINIMA_OUTLET = 20  # Piso para outlets sin historial de ventas
MAX_UNIDADES_SKU_POR_OUTLET = 5  # Evita saturar un outlet con un solo SKU

# --- Filtros logísticos ---
# Un envío de 3 unidades a 80 km cuesta más en flete que la mercancía que
# mueve. Estos dos filtros descartan los traslados económicamente absurdos.
MIN_UNIDADES_POR_ENVIO = 10
MAX_KM_TRASLADO = 100


# =============================================================================
# CARGA
# =============================================================================

def cargar_datos(con: sqlite3.Connection) -> pd.DataFrame:
    """
    Trae inventario, catálogo y velocidad de venta en una sola consulta.

    La necesidad y el exceso se calculan en SQL contra los mínimos y máximos
    parametrizados. Un SKU descontinuado no tiene parametrización, así que
    todo su stock cuenta como exceso evacuable.
    """
    query = """
        SELECT
            i.tienda_id,
            t.nombre        AS tienda,
            t.ciudad,
            t.formato,
            t.genero_tienda,
            i.sku,
            p.referencia,
            p.categoria,
            p.genero        AS genero_producto,
            p.talla,
            p.color,
            p.activo,
            i.stock,
            i.minimo,
            i.maximo,
            MAX(0, i.minimo - i.stock)                      AS necesidad,
            CASE WHEN p.activo = 1 THEN MAX(0, i.stock - i.maximo)
                 ELSE i.stock END                           AS exceso,
            COALESCE(v.unidades_90d, 0)                     AS venta_90d
        FROM inventario i
        JOIN tiendas   t ON t.tienda_id = i.tienda_id
        JOIN productos p ON p.sku       = i.sku
        LEFT JOIN (
            SELECT tienda_id, SUM(unidades) AS unidades_90d
            FROM ventas
            WHERE dias_atras <= 90
            GROUP BY tienda_id
        ) v ON v.tienda_id = i.tienda_id
    """
    return pd.read_sql_query(query, con)


# =============================================================================
# CAPACIDAD DE OUTLETS
# =============================================================================

def calcular_capacidad_outlets(df: pd.DataFrame) -> dict[str, float]:
    """
    Cuánto puede absorber cada outlet, según su velocidad real de venta.

    Un tope fijo por outlet es un error clásico: llena de mercancía puntos
    que no rotan y deja vacíos los que sí. La capacidad se deriva de las
    ventas de los últimos 90 días proyectadas a los días de cobertura
    permitidos, descontando lo que ya tiene en stock.
    """
    outlets = df[df["formato"] == "OUTLET"]
    capacidad: dict[str, float] = {}

    for tienda_id, grupo in outlets.groupby("tienda_id"):
        venta_90d = grupo["venta_90d"].iloc[0]
        velocidad_diaria = venta_90d / 90 if venta_90d else 0
        techo = velocidad_diaria * DIAS_COBERTURA_OUTLET
        stock_actual = grupo["stock"].sum()
        disponible = max(techo - stock_actual, CAPACIDAD_MINIMA_OUTLET)
        capacidad[tienda_id] = disponible

    return capacidad


# =============================================================================
# MOTOR
# =============================================================================

def generar_plan(df: pd.DataFrame) -> pd.DataFrame:
    plan: list[dict] = []

    meta = (
        df.drop_duplicates("tienda_id")
        .set_index("tienda_id")[["tienda", "ciudad", "formato", "genero_tienda"]]
        .to_dict("index")
    )
    info_sku = (
        df.drop_duplicates("sku")
        .set_index("sku")[["referencia", "categoria", "genero_producto", "talla", "color"]]
        .to_dict("index")
    )
    sku_activo = df.drop_duplicates("sku").set_index("sku")["activo"].astype(bool).to_dict()

    es_outlet = df["formato"] == "OUTLET"

    # Estado mutable: se va descontando conforme se asignan traslados, para
    # que ninguna unidad se comprometa dos veces.
    necesidad = {
        (r.sku, r.tienda_id): r.necesidad
        for r in df[(~es_outlet) & (df["necesidad"] > 0)].itertuples()
    }
    disponible = {
        (r.sku, r.tienda_id): r.stock
        for r in df[es_outlet & (df["stock"] > 0)].itertuples()
    }
    excedente = {
        (r.sku, r.tienda_id): r.exceso
        for r in df[(~es_outlet) & (df["exceso"] > 0)].itertuples()
    }
    capacidad_outlet = calcular_capacidad_outlets(df)

    # Índices SKU -> tiendas, para no recorrer el DataFrame en cada iteración
    idx_outlet = defaultdict(list)
    for sku, tid in disponible:
        idx_outlet[sku].append(tid)

    idx_exceso = defaultdict(list)
    for sku, tid in excedente:
        idx_exceso[sku].append(tid)

    outlets_por_sku = defaultdict(list)
    for r in df[es_outlet].itertuples():
        outlets_por_sku[r.genero_producto].append(r.tienda_id)
    outlets_receptores = {
        genero: sorted(set(ids)) for genero, ids in outlets_por_sku.items()
    }

    def compatible(genero_producto: str, tienda_id: str) -> bool:
        destino = meta[tienda_id]["genero_tienda"]
        return destino in COMPATIBILIDAD.get(genero_producto, set())

    def registrar(prioridad, motivo, sku, origen, destino, unidades):
        km = distancia_km(meta[origen]["ciudad"], meta[destino]["ciudad"])
        datos_sku = info_sku[sku]
        plan.append(
            {
                "prioridad": prioridad,
                "motivo": motivo,
                "sku": sku,
                "referencia": datos_sku["referencia"],
                "categoria": datos_sku["categoria"],
                "talla": datos_sku["talla"],
                "color": datos_sku["color"],
                "unidades": int(unidades),
                "origen": meta[origen]["tienda"],
                "ciudad_origen": meta[origen]["ciudad"],
                "destino": meta[destino]["tienda"],
                "ciudad_destino": meta[destino]["ciudad"],
                "km": km,
                "horas_estimadas": horas_viaje(km),
            }
        )

    # -------------------------------------------------------------------------
    # ETAPA 1 — Recuperación: Outlet -> tienda regular
    # Producto activo atrapado en un outlet, donde se vende con descuento,
    # devuelto a una tienda que lo necesita a precio pleno. Es la etapa de
    # mayor retorno por unidad movida, por eso va primero.
    # -------------------------------------------------------------------------
    for (sku, destino), falta in sorted(necesidad.items(), key=lambda x: -x[1]):
        if falta <= 0:
            continue
        genero = info_sku[sku]["genero_producto"]
        if not compatible(genero, destino):
            continue

        candidatos = [
            t for t in idx_outlet.get(sku, []) if disponible.get((sku, t), 0) > 0
        ]
        if not candidatos:
            continue

        origen = min(
            candidatos,
            key=lambda t: distancia_km(meta[t]["ciudad"], meta[destino]["ciudad"]),
        )
        if distancia_km(meta[origen]["ciudad"], meta[destino]["ciudad"]) > MAX_KM_TRASLADO:
            continue

        envio = min(disponible[(sku, origen)], falta)
        if envio >= 1:
            registrar("1-RECUPERACION", "Producto activo en outlet", sku, origen, destino, envio)
            disponible[(sku, origen)] -= envio
            necesidad[(sku, destino)] -= envio

    # -------------------------------------------------------------------------
    # ETAPA 2 — Rebalanceo: tienda regular -> tienda regular
    # Excedente por encima del máximo movido a donde hay faltante. No cambia
    # el inventario total de la red, solo lo pone donde puede venderse.
    # -------------------------------------------------------------------------
    for (sku, destino), falta in sorted(necesidad.items(), key=lambda x: -x[1]):
        if falta <= 0:
            continue
        genero = info_sku[sku]["genero_producto"]
        if not compatible(genero, destino):
            continue

        candidatos = [
            t
            for t in idx_exceso.get(sku, [])
            if t != destino and excedente.get((sku, t), 0) > 0
        ]
        if not candidatos:
            continue

        origen = min(
            candidatos,
            key=lambda t: distancia_km(meta[t]["ciudad"], meta[destino]["ciudad"]),
        )
        if distancia_km(meta[origen]["ciudad"], meta[destino]["ciudad"]) > MAX_KM_TRASLADO:
            continue

        envio = min(excedente[(sku, origen)], falta)
        if envio >= 1:
            registrar("2-REBALANCEO", "Exceso hacia faltante", sku, origen, destino, envio)
            excedente[(sku, origen)] -= envio
            necesidad[(sku, destino)] -= envio

    # -------------------------------------------------------------------------
    # ETAPA 3 — Evacuación: tienda regular -> Outlet
    # Producto descontinuado que ocupa espacio en tienda regular. Va al canal
    # de liquidación, repartido entre outlets según su capacidad de absorción
    # y sin concentrar demasiadas unidades del mismo SKU en un solo punto.
    # -------------------------------------------------------------------------
    evacuables = [
        ((sku, tid), cantidad)
        for (sku, tid), cantidad in excedente.items()
        if cantidad > 0 and not sku_activo.get(sku, True)
    ]

    for (sku, origen), cantidad in sorted(evacuables, key=lambda x: -x[1]):
        if cantidad <= 0:
            continue
        genero = info_sku[sku]["genero_producto"]

        receptores = [
            t
            for t in outlets_receptores.get(genero, [])
            if capacidad_outlet.get(t, 0) > 0
            and compatible(genero, t)
            and distancia_km(meta[origen]["ciudad"], meta[t]["ciudad"]) <= MAX_KM_TRASLADO
        ]
        receptores.sort(
            key=lambda t: distancia_km(meta[origen]["ciudad"], meta[t]["ciudad"])
        )

        for destino in receptores:
            if cantidad <= 0:
                break
            envio = min(cantidad, MAX_UNIDADES_SKU_POR_OUTLET, capacidad_outlet[destino])
            if envio >= 1:
                registrar("3-EVACUACION", "Descontinuado a liquidacion", sku, origen, destino, envio)
                capacidad_outlet[destino] -= envio
                cantidad -= envio
                excedente[(sku, origen)] -= envio

    return pd.DataFrame(plan)


# =============================================================================
# FILTROS Y SALIDA
# =============================================================================

def aplicar_filtros(plan: pd.DataFrame) -> pd.DataFrame:
    """
    Descarta los traslados que no se sostienen económicamente.

    El filtro es por par origen-destino, no por línea: veinte líneas de una
    unidad entre las mismas dos tiendas sí llenan un bulto, aunque cada
    línea por separado parezca insignificante.
    """
    if plan.empty:
        return plan

    antes = len(plan)
    plan = plan[plan["km"] <= MAX_KM_TRASLADO].copy()

    volumen = plan.groupby(["origen", "destino"])["unidades"].transform("sum")
    plan = plan[volumen >= MIN_UNIDADES_POR_ENVIO].copy()

    print(f"Filtros: {antes} -> {len(plan)} lineas ({antes - len(plan)} descartadas)")
    return plan.sort_values(["prioridad", "ciudad_origen", "origen", "referencia"])


def main() -> None:
    if not RUTA_DB.exists():
        raise SystemExit("No existe inventario.db. Ejecuta primero: python generar_datos.py")

    con = sqlite3.connect(RUTA_DB)
    try:
        print("Cargando inventario...")
        df = cargar_datos(con)
        print(f"  {len(df)} filas de inventario en {df['tienda_id'].nunique()} tiendas")

        print("Generando plan...")
        plan = generar_plan(df)
        plan = aplicar_filtros(plan)
    finally:
        con.close()

    if plan.empty:
        print("No se generaron traslados con los parametros actuales.")
        return

    plan.to_csv(RUTA_SALIDA, index=False, encoding="utf-8-sig")

    print(f"\nPlan exportado a {RUTA_SALIDA}")
    print(f"Lineas:   {len(plan)}")
    print(f"Unidades: {int(plan['unidades'].sum())}")
    print("\nPor prioridad:")
    print(plan.groupby("prioridad").agg(
        lineas=("unidades", "size"), unidades=("unidades", "sum")
    ).to_string())


if __name__ == "__main__":
    main()
