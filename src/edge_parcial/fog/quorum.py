"""Quórum de mayoría estricta (docs/DISENO.md §24): Q(N) = ⌊N/2⌋ + 1."""

from collections.abc import Sequence


def quorum(n: int) -> int:
    """Votos mínimos para alerta con N fuentes. Para N = 3: ⌊3/2⌋ + 1 = 2."""
    if n < 1:
        raise ValueError(f"N debe ser >= 1 (recibido {n})")
    return n // 2 + 1


def decidir(votos: Sequence[bool], q: int) -> tuple[int, bool]:
    """(n_true, alerta): alerta si al menos Q votos son True en la misma ventana."""
    n_true = sum(bool(v) for v in votos)
    return n_true, n_true >= q
