"""Rejilla única de ventanas sobre el reloj monotónico (docs/DISENO.md §24)."""

from dataclasses import dataclass

S_A_NS = 1_000_000_000


@dataclass(frozen=True)
class Rejilla:
    """Ventanas [t0 + k·W, t0 + (k+1)·W), cerradas por la izquierda, compartidas por todas las fuentes."""

    t0_ns: int
    ventana_ns: int = S_A_NS

    def indice(self, t_ns: int) -> int:
        """Ventana de un instante (negativo si es anterior a t0). Un fotograma exactamente
        en el límite pertenece a la ventana que empieza ahí."""
        return (t_ns - self.t0_ns) // self.ventana_ns

    def inicio(self, k: int) -> int:
        return self.t0_ns + k * self.ventana_ns

    def fin(self, k: int) -> int:
        return self.t0_ns + (k + 1) * self.ventana_ns
