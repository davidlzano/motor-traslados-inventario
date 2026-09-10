"""
Coordenadas de ciudades colombianas y cálculo de distancias geodésicas.

Las coordenadas son información pública. El cálculo usa la fórmula de
Haversine, que da la distancia sobre la superficie terrestre entre dos
puntos a partir de su latitud y longitud.

Se implementa a mano en lugar de usar geopy para evitar una dependencia
externa en un cálculo que son seis líneas de trigonometría.
"""

import math

RADIO_TIERRA_KM = 6371

CIUDADES = {
    "MEDELLIN": (6.244, -75.573),
    "BOGOTA": (4.711, -74.072),
    "CALI": (3.451, -76.531),
    "BARRANQUILLA": (10.968, -74.781),
    "CARTAGENA": (10.391, -75.479),
    "BUCARAMANGA": (7.119, -73.122),
    "PEREIRA": (4.813, -75.694),
    "MANIZALES": (5.068, -75.517),
    "ARMENIA": (4.533, -75.681),
    "IBAGUE": (4.438, -75.232),
    "CUCUTA": (7.893, -72.507),
    "VILLAVICENCIO": (4.142, -73.626),
    "NEIVA": (2.927, -75.281),
    "PASTO": (1.213, -77.281),
    "MONTERIA": (8.747, -75.881),
    "SANTA MARTA": (11.240, -74.199),
    "VALLEDUPAR": (10.463, -73.253),
    "SINCELEJO": (9.304, -75.397),
    "POPAYAN": (2.441, -76.606),
    "TUNJA": (5.535, -73.367),
    # Área metropolitana de Medellín
    "BELLO": (6.337, -75.557),
    "ITAGUI": (6.174, -75.609),
    "ENVIGADO": (6.175, -75.591),
    "SABANETA": (6.151, -75.615),
    "RIONEGRO": (6.155, -75.373),
    # Área metropolitana de Bogotá
    "SOACHA": (4.578, -74.212),
    "CHIA": (4.863, -74.051),
    "ZIPAQUIRA": (5.026, -73.991),
    "FUSAGASUGA": (4.336, -74.363),
    # Eje cafetero y Valle
    "DOSQUEBRADAS": (4.836, -75.680),
    "CARTAGO": (4.746, -75.911),
    "TULUA": (4.084, -76.198),
    "PALMIRA": (3.539, -76.303),
    "BUGA": (3.900, -76.297),
    "YUMBO": (3.583, -76.491),
    "JAMUNDI": (3.261, -76.535),
    # Costa
    "SOLEDAD": (10.917, -74.764),
    "MALAMBO": (10.859, -74.774),
    "TURBACO": (10.334, -75.441),
    "CIENAGA": (11.007, -74.247),
}

# Velocidades promedio para estimar tiempo de viaje.
# El trayecto urbano es más lento por tráfico y semáforos; el interurbano
# se hace por carretera. El umbral separa ambos regímenes.
VELOCIDAD_URBANA_KMH = 22
VELOCIDAD_INTERURBANA_KMH = 55
UMBRAL_URBANO_KM = 45

_cache_distancias: dict[tuple[str, str], float] = {}


def distancia_km(ciudad_a: str, ciudad_b: str) -> float:
    """
    Distancia geodésica en kilómetros entre dos ciudades.

    Devuelve 0.1 para traslados dentro de la misma ciudad (no cero, para
    que las comparaciones por distancia no se rompan con divisiones).
    Devuelve infinito si alguna ciudad no está en el mapa, lo que hace que
    el par quede automáticamente descartado por el filtro de distancia.

    Los resultados se cachean: con cientos de tiendas, los mismos pares
    de ciudades se consultan miles de veces.
    """
    a = str(ciudad_a).strip().upper()
    b = str(ciudad_b).strip().upper()

    if a == b:
        return 0.1

    clave = (a, b) if a < b else (b, a)
    if clave in _cache_distancias:
        return _cache_distancias[clave]

    p1, p2 = CIUDADES.get(a), CIUDADES.get(b)
    if p1 is None or p2 is None:
        return float("inf")

    rad = math.pi / 180
    dlat = (p2[0] - p1[0]) * rad
    dlon = (p2[1] - p1[1]) * rad
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(p1[0] * rad) * math.cos(p2[0] * rad) * math.sin(dlon / 2) ** 2
    )
    distancia = round(2 * RADIO_TIERRA_KM * math.asin(math.sqrt(h)), 2)

    _cache_distancias[clave] = distancia
    return distancia


def horas_viaje(km: float) -> float:
    """Tiempo estimado de viaje según el régimen de velocidad aplicable."""
    if km == float("inf"):
        return float("inf")
    velocidad = VELOCIDAD_URBANA_KMH if km < UMBRAL_URBANO_KM else VELOCIDAD_INTERURBANA_KMH
    return round(km / velocidad, 1)
