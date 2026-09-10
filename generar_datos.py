"""
Genera una red ficticia de tiendas e inventario en una base SQLite local.

El motor de traslados está diseñado para leer de una base de datos, no de
archivos sueltos. Este script crea esa base con datos sintéticos para que
el proyecto se pueda ejecutar sin depender de ningún sistema externo.

Uso:
    python generar_datos.py
"""

import random
import sqlite3
from pathlib import Path

from ciudades import CIUDADES

RUTA_DB = Path("inventario.db")
SEMILLA = 42  # Fija para que los resultados sean reproducibles

N_TIENDAS = 120
N_REFERENCIAS = 80

FORMATOS = ["ESTELAR", "ESTANDAR", "OUTLET"]
PESOS_FORMATO = [0.25, 0.55, 0.20]

# Género del producto -> tipos de tienda que pueden recibirlo.
# Impide que una tienda de adulto reciba producto infantil.
COMPATIBILIDAD = {
    "HOMBRE": ["ADULTO", "MIXTA"],
    "MUJER": ["ADULTO", "MIXTA"],
    "ADULTO UNISEX": ["ADULTO", "MIXTA"],
    "NINO": ["INFANTIL", "MIXTA"],
    "NINA": ["INFANTIL", "MIXTA"],
    "BEBE": ["INFANTIL", "MIXTA"],
}

GENEROS_TIENDA = ["ADULTO", "INFANTIL", "MIXTA"]
CATEGORIAS = ["CAMISETA", "PANTALON", "CHAQUETA", "VESTIDO", "CALZADO", "ACCESORIO"]
TALLAS = ["XS", "S", "M", "L", "XL"]
COLORES = ["NEGRO", "BLANCO", "AZUL", "ROJO", "VERDE", "GRIS"]


def crear_esquema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP TABLE IF EXISTS tiendas;
        DROP TABLE IF EXISTS productos;
        DROP TABLE IF EXISTS inventario;
        DROP TABLE IF EXISTS ventas;

        CREATE TABLE tiendas (
            tienda_id      TEXT PRIMARY KEY,
            nombre         TEXT NOT NULL,
            ciudad         TEXT NOT NULL,
            formato        TEXT NOT NULL,
            genero_tienda  TEXT NOT NULL
        );

        CREATE TABLE productos (
            sku        TEXT PRIMARY KEY,
            referencia TEXT NOT NULL,
            categoria  TEXT NOT NULL,
            genero     TEXT NOT NULL,
            talla      TEXT NOT NULL,
            color      TEXT NOT NULL,
            activo     INTEGER NOT NULL
        );

        CREATE TABLE inventario (
            tienda_id TEXT NOT NULL,
            sku       TEXT NOT NULL,
            stock     INTEGER NOT NULL,
            minimo    INTEGER NOT NULL,
            maximo    INTEGER NOT NULL,
            PRIMARY KEY (tienda_id, sku)
        );

        CREATE TABLE ventas (
            tienda_id  TEXT NOT NULL,
            sku        TEXT NOT NULL,
            unidades   INTEGER NOT NULL,
            dias_atras INTEGER NOT NULL
        );

        CREATE INDEX idx_inv_sku ON inventario(sku);
        CREATE INDEX idx_ven_tienda ON ventas(tienda_id);
        """
    )


def generar(con: sqlite3.Connection) -> None:
    rnd = random.Random(SEMILLA)
    ciudades = list(CIUDADES.keys())

    # --- Tiendas ---
    tiendas = []
    for i in range(1, N_TIENDAS + 1):
        ciudad = rnd.choice(ciudades)
        formato = rnd.choices(FORMATOS, weights=PESOS_FORMATO)[0]
        genero = rnd.choice(GENEROS_TIENDA)
        tiendas.append(
            (f"T{i:03d}", f"{formato.title()} {ciudad.title()} {i:03d}", ciudad, formato, genero)
        )
    con.executemany("INSERT INTO tiendas VALUES (?,?,?,?,?)", tiendas)

    # --- Productos ---
    # El 30% son descontinuados: producto que ya no se repone y hay que evacuar.
    productos = []
    for i in range(1, N_REFERENCIAS + 1):
        referencia = f"REF{i:04d}"
        categoria = rnd.choice(CATEGORIAS)
        genero = rnd.choice(list(COMPATIBILIDAD.keys()))
        activo = 0 if rnd.random() < 0.30 else 1
        for talla in rnd.sample(TALLAS, k=rnd.randint(2, 5)):
            color = rnd.choice(COLORES)
            sku = f"{referencia}-{talla}-{color[:3]}"
            productos.append((sku, referencia, categoria, genero, talla, color, activo))
    con.executemany("INSERT INTO productos VALUES (?,?,?,?,?,?,?)", productos)

    # --- Inventario ---
    # Cada tienda tiene una muestra del catálogo. Los mínimos y máximos solo
    # aplican a producto activo: lo descontinuado no se repone.
    inventario = []
    for tienda_id, _, _, formato, genero_tienda in tiendas:
        compatibles = [
            p for p in productos if genero_tienda in COMPATIBILIDAD[p[3]]
        ]
        muestra = rnd.sample(compatibles, k=min(len(compatibles), rnd.randint(40, 90)))
        for sku, _, _, _, _, _, activo in muestra:
            if activo and formato != "OUTLET":
                minimo = rnd.randint(2, 6)
                maximo = minimo + rnd.randint(4, 14)
            else:
                minimo = maximo = 0
            stock = rnd.randint(0, 25)
            inventario.append((tienda_id, sku, stock, minimo, maximo))
    con.executemany("INSERT INTO inventario VALUES (?,?,?,?,?)", inventario)

    # --- Ventas de los últimos 90 días ---
    # Alimentan el cálculo de capacidad de absorción de los outlets.
    ventas = []
    for tienda_id, sku, stock, _, _ in inventario:
        if rnd.random() < 0.55:
            for _ in range(rnd.randint(1, 6)):
                ventas.append(
                    (tienda_id, sku, rnd.randint(1, 4), rnd.randint(0, 90))
                )
    con.executemany("INSERT INTO ventas VALUES (?,?,?,?)", ventas)

    con.commit()
    print(f"Tiendas:     {len(tiendas):>6}")
    print(f"SKU:         {len(productos):>6}")
    print(f"Inventario:  {len(inventario):>6} filas")
    print(f"Ventas 90d:  {len(ventas):>6} registros")


def main() -> None:
    if RUTA_DB.exists():
        RUTA_DB.unlink()
    con = sqlite3.connect(RUTA_DB)
    try:
        crear_esquema(con)
        generar(con)
        print(f"\nBase creada en {RUTA_DB.resolve()}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
