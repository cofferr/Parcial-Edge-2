"""Pruebas del parser MJPEG puro (sin sockets)."""

import pytest
from servidor_falso import (
    cabecera_http,
    cabeceras_esp32,
    hacer_jpeg,
    jpeg_con_app_falso,
    parte,
    respuesta_captura,
    trozos_aleatorios,
)

from edge_parcial.acquisition.mjpeg import ErrorProtocolo, ParserMJPEG, jpeg_valido


def alimentar(parser, trozos, t0=1_000, paso=10):
    """Alimenta con marcas t0, t0+paso... y devuelve (fotogramas, marcas usadas)."""
    fotogramas, marcas = [], []
    for i, t in enumerate(trozos):
        marcas.append(t0 + i * paso)
        fotogramas += parser.feed(t, marcas[-1])
    return fotogramas, marcas


def flujo(jpegs, **kw):
    return cabecera_http() + b"".join(parte(j, **kw) for j in jpegs)


@pytest.mark.parametrize("semilla", range(8))
def test_fragmentacion_aleatoria_con_content_length(semilla):
    jpegs = [hacer_jpeg(i) for i in range(12)]
    datos = flujo(jpegs, cabeceras=None)
    fs, _ = alimentar(ParserMJPEG(), trozos_aleatorios(datos, semilla))
    assert [f.payload for f in fs] == jpegs
    assert all(f.jpeg_valid and f.error is None for f in fs)


def test_trozos_de_un_byte():
    jpegs = [hacer_jpeg(i) for i in range(3)]
    fs, _ = alimentar(ParserMJPEG(), [bytes([b]) for b in flujo(jpegs)])
    assert [f.payload for f in fs] == jpegs


@pytest.mark.parametrize("semilla", range(8))
def test_sin_content_length_recorre_marcadores(semilla):
    jpegs = [hacer_jpeg(i, 96, 72) for i in range(10)]
    datos = flujo(jpegs, con_cl=False)
    fs, _ = alimentar(ParserMJPEG(), trozos_aleatorios(datos, semilla, 500))
    assert [f.payload for f in fs] == jpegs
    assert all(f.jpeg_valid for f in fs)


def test_sin_content_length_un_byte():
    jpegs = [hacer_jpeg(i) for i in range(3)]
    fs, _ = alimentar(ParserMJPEG(), [bytes([b]) for b in flujo(jpegs, con_cl=False)])
    assert [f.payload for f in fs] == jpegs


def test_ffd9_dentro_de_miniatura_no_es_el_eoi():
    jpegs = [jpeg_con_app_falso(hacer_jpeg(i)) for i in range(4)]
    assert all(b"\xff\xd9" in j[:30] for j in jpegs)
    fs, _ = alimentar(ParserMJPEG(), trozos_aleatorios(flujo(jpegs, con_cl=False), 3))
    assert [f.payload for f in fs] == jpegs


def test_con_content_length_no_se_recorre_el_jpeg(monkeypatch):
    from edge_parcial.acquisition import mjpeg

    def prohibido(*a, **k):
        raise AssertionError("no debe recorrer marcadores con Content-Length")

    monkeypatch.setattr(mjpeg._Recorrido, "avanzar", prohibido)
    fs, _ = alimentar(ParserMJPEG(), [flujo([hacer_jpeg(1)])])
    assert len(fs) == 1


def test_con_content_length_usa_exactamente_n_bytes_aunque_el_jpeg_sea_raro():
    # Carga con un FFD9 en medio: con Content-Length se respetan los N bytes.
    jpeg = b"\xff\xd8" + b"\x00" * 10 + b"\xff\xd9" + b"\x11" * 10 + b"\xff\xd9"
    fs, _ = alimentar(ParserMJPEG(), [flujo([jpeg])])
    assert fs[0].payload == jpeg and fs[0].jpeg_valid


def test_jpeg_corrupto_con_content_length():
    malo = b"\x00\x01" + hacer_jpeg(1)[2:-2] + b"\x00\x00"
    fs, _ = alimentar(ParserMJPEG(), [flujo([malo, hacer_jpeg(2)])])
    assert fs[0].payload == malo and not fs[0].jpeg_valid
    assert "SOI/EOI" in fs[0].error
    assert fs[1].jpeg_valid  # el siguiente se sincroniza bien


def test_jpeg_corrupto_sin_content_length():
    malo = b"\xff\xd8" + b"\x12\x34" * 30 + b"\xff\xd9"
    buenos = [hacer_jpeg(1), hacer_jpeg(2)]
    datos = cabecera_http() + parte(buenos[0], con_cl=False)
    datos += parte(malo, con_cl=False) + parte(buenos[1], con_cl=False)
    fs, _ = alimentar(ParserMJPEG(), trozos_aleatorios(datos, 5, 100))
    assert [f.payload for f in fs] == [buenos[0], malo, buenos[1]]
    assert [f.jpeg_valid for f in fs] == [True, False, True]
    assert "corrupto" in fs[1].error


def test_cabeceras_x_presentes_y_ausentes():
    j = hacer_jpeg(1)
    datos = cabecera_http() + parte(j, cabeceras=cabeceras_esp32(3)) + parte(j)
    fs, _ = alimentar(ParserMJPEG(), [datos])
    assert fs[0].cabeceras["x-capture-us"] == "1003"
    assert fs[0].cabeceras["x-rssi-dbm"] == "-53"
    assert "x-capture-us" not in fs[1].cabeceras


def test_header_bytes_incluye_delimitador_y_cabeceras():
    j = hacer_jpeg(1)
    p = parte(j)
    fs, _ = alimentar(ParserMJPEG(), [cabecera_http() + p])
    assert fs[0].header_bytes == len(p) - len(j) - 2  # sin el CRLF posterior


def test_marcas_t_first_t_last_y_n_recv():
    j = hacer_jpeg(1)
    p = parte(j)
    # Trozos: cabecera HTTP | "--fra" | resto de la cabecera y 100 B | resto del JPEG
    cortes = [
        cabecera_http(),
        p[:5],
        p[5 : len(p) - len(j) + 100],
        p[len(p) - len(j) + 100 :],
    ]
    parser = ParserMJPEG()
    fs = []
    for t, c in zip([10, 20, 30, 40], cortes):
        fs += parser.feed(c, t)
    assert len(fs) == 1
    f = fs[0]
    assert f.t_first_ns == 20  # recv que traía el primer byte del delimitador
    assert f.t_last_ns == 40  # recv que traía el último byte de la carga
    assert f.n_recv == 3


def test_fotograma_en_un_solo_recv_tiene_n_recv_1():
    fs, _ = alimentar(ParserMJPEG(), [flujo([hacer_jpeg(1)])])
    assert fs[0].n_recv == 1 and fs[0].t_first_ns == fs[0].t_last_ns


def test_crlf_de_la_parte_anterior_no_cuenta_como_primer_byte():
    j1, j2 = hacer_jpeg(1), hacer_jpeg(2)
    p1, p2 = parte(j1), parte(j2)
    parser = ParserMJPEG()
    fs = parser.feed(cabecera_http() + p1[:-2], 10)
    assert fs and fs[0].t_last_ns == 10
    parser.feed(b"\r\n", 100)  # solo el CRLF de la parte 1, mucho antes de la parte 2
    fs = parser.feed(p2, 500)
    assert fs[0].t_first_ns == 500  # el retardo previo no se atribuye a la parte 2


def test_primer_byte_y_ultimo_en_recv_distintos_con_misma_marca_monotona():
    jpegs = [hacer_jpeg(i) for i in range(5)]
    fs, _ = alimentar(ParserMJPEG(), trozos_aleatorios(flujo(jpegs), 11, 90))
    for f in fs:
        assert f.t_first_ns <= f.t_last_ns
        assert f.n_recv >= 1
    firsts = [f.t_first_ns for f in fs]
    assert firsts == sorted(firsts)


def test_boundary_con_comillas_y_autodeteccion():
    j = hacer_jpeg(1)
    cab = b'HTTP/1.0 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary="abc"\r\n\r\n'
    fs, _ = alimentar(ParserMJPEG(), [cab + parte(j, boundary="abc")])
    assert fs[0].payload == j
    sin = b"HTTP/1.0 200 OK\r\n\r\n"
    p = ParserMJPEG()
    fs, _ = alimentar(p, [sin + parte(j, boundary="xyz")])
    assert fs[0].payload == j and p.delimitador == b"--xyz"


def test_delimitador_final_termina_el_flujo():
    j = hacer_jpeg(1)
    fs, _ = alimentar(ParserMJPEG(), [flujo([j]) + b"--frame--\r\n"])
    assert len(fs) == 1


@pytest.mark.parametrize(
    "datos",
    [
        b"HTTP/1.1 404 Not Found\r\n\r\n",
        b"basura sin http\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n",
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
            b"Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n"
        ),
        cabecera_http() + b"BASURA-QUE-NO-ES-DELIMITADOR\r\n",
    ],
)
def test_errores_de_protocolo(datos):
    with pytest.raises(ErrorProtocolo):
        ParserMJPEG().feed(datos, 1)


def test_bytes_pendientes_y_totales():
    j = hacer_jpeg(1)
    p = parte(j)
    parser = ParserMJPEG()
    parser.feed(cabecera_http() + p + p[:30], 1)
    assert parser.bytes_totales == len(cabecera_http()) + len(p) + 30
    assert parser.bytes_pendientes() == 30


def test_captura_con_content_length_y_cabeceras():
    j = hacer_jpeg(1)
    resp = respuesta_captura(j, cabeceras=cabeceras_esp32(1, flush=True))
    p = ParserMJPEG("captura")
    fs, _ = alimentar(p, trozos_aleatorios(resp, 4, 60))
    assert fs[0].payload == j and fs[0].jpeg_valid
    assert fs[0].cabeceras["x-flush-us"] == "31"
    assert fs[0].header_bytes == len(resp) - len(j)


def test_captura_sin_content_length_termina_al_cerrar():
    j = hacer_jpeg(1)
    p = ParserMJPEG("captura")
    fs, _ = alimentar(p, trozos_aleatorios(respuesta_captura(j, con_cl=False), 2, 80))
    assert fs == []
    fs = p.fin_de_flujo()
    assert fs[0].payload == j and fs[0].jpeg_valid


def test_captura_sin_cuerpo():
    p = ParserMJPEG("captura")
    p.feed(respuesta_captura(b"", con_cl=False), 1)
    with pytest.raises(ErrorProtocolo):
        p.fin_de_flujo()


def test_jpeg_valido():
    assert jpeg_valido(hacer_jpeg(1))
    assert not jpeg_valido(b"\xff\xd8")
    assert not jpeg_valido(b"abcdef")


@pytest.mark.parametrize("trozo", [10_000, 1])
def test_boundary_con_prefijo_doble_como_droidcam(trozo):
    # DroidCam declara boundary=--dcmjpeg y envía "--dcmjpeg" (no "----dcmjpeg").
    jpegs = [hacer_jpeg(i) for i in range(3)]
    datos = cabecera_http(boundary="--dcmjpeg") + b"".join(
        parte(j, boundary="dcmjpeg") for j in jpegs
    )
    trozos = [datos[i : i + trozo] for i in range(0, len(datos), trozo)]
    fs, _ = alimentar(ParserMJPEG(), trozos)
    assert [f.payload for f in fs] == jpegs


def test_boundary_con_prefijo_doble_segun_rfc_sigue_valiendo():
    jpegs = [hacer_jpeg(i) for i in range(2)]
    datos = cabecera_http(boundary="--x") + b"".join(
        parte(j, boundary="--x") for j in jpegs
    )
    fs, _ = alimentar(ParserMJPEG(), [datos])
    assert [f.payload for f in fs] == jpegs
