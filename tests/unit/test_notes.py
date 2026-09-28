from builders import make_geo, make_meta
from japan_reader.notes import (
    CosaData,
    LugarData,
    OtroData,
    add_source,
    compose_content,
    dump_data,
    labels_for,
    load_data,
    render_failure,
    render_generated,
    source_entry,
)


def _lugar(**overrides):
    base = dict(
        nombre="Ichiran Shibuya", nombre_local="一蘭 渋谷店", ciudad="Tokio", region="Kanto", categoria="comida",
        resumen="Ramen <b>tonkotsu</b> en cubículos", que_hacer="Pedir extra de cerdo", consejos=["Ir antes de las 11"],
        precio_aprox="¥1000", place=make_geo(), fuentes=[source_entry("b1", make_meta(), "Primer vídeo")],
    )
    return LugarData(**(base | overrides))


def test_render_lugar_sections_and_escaping():
    html = render_generated(_lugar())
    assert "<h2>Resumen</h2>" in html
    assert "Ramen &lt;b&gt;tonkotsu&lt;/b&gt;" in html
    assert "<h2>Qué hacer / comer</h2>" in html
    assert "<li>Precio aproximado: ¥1000</li>" in html
    assert 'href="https://maps.google.com/?cid=P1"' in html
    assert "<h2>Fuentes</h2>" in html and "viajero" in html and "Primer vídeo" in html


def test_render_cosa_and_otro():
    cosa = CosaData(nombre="Kit Kat matcha", categoria="souvenirs", resumen="Chocolatina", donde=["Konbini"], fuentes=[])
    assert "<h2>Dónde conseguirlo</h2>" in render_generated(cosa)
    otro = OtroData(titulo="Propinas", contenido="En Japón no se dan propinas", fuentes=[])
    assert "no se dan propinas" in render_generated(otro)


def test_compose_new_note_has_empty_user_section():
    assert compose_content("<p>gen</p>", None) == "<p>gen</p><h2>Mis notas</h2><p></p>"


def test_compose_keeps_user_notes_even_if_editor_rewrote_heading():
    """Review Focus 1."""
    existing = "<p>viejo</p><h2><strong>Mis notas</strong></h2><p>Reservar el martes</p>"
    assert compose_content("<p>nuevo</p>", existing) == "<p>nuevo</p><h2>Mis notas</h2><p>Reservar el martes</p>"


def test_compose_without_heading_keeps_everything():
    assert compose_content("<p>nuevo</p>", "<p>todo lo que había</p>") == "<p>nuevo</p><h2>Mis notas</h2><p>todo lo que había</p>"


def test_add_source_appends_or_replaces():
    data = _lugar()
    assert add_source(data, source_entry("b2", make_meta(url="https://youtu.be/2"), "Segundo")) is True
    assert add_source(data, source_entry("b1", make_meta(), "Primero actualizado")) is False
    assert [f.aporte for f in data.fuentes] == ["Primero actualizado", "Segundo"]


def test_dump_and_load_roundtrip():
    for data in (_lugar(), CosaData(nombre="X", categoria="otros", resumen="r"), OtroData(titulo="t", contenido="c")):
        assert load_data(dump_data(data)) == data


def test_labels_for_lugar_and_cosa():
    labels = labels_for(_lugar())
    assert labels["geolocation"] == "35.66,139.7"
    assert labels["googlePlaceId"] == "P1"
    assert labels["googleMaps"] == "https://maps.google.com/?cid=P1"
    assert labels["jrTipo"] == "lugar" and labels["fuentes"] == "1"
    assert labels["iconClass"] == "bx bx-bowl-hot"
    assert labels["nombreLocal"] == "一蘭 渋谷店"
    assert "geolocation" not in labels_for(_lugar(place=None))
    cosa = labels_for(CosaData(nombre="CoCo Ichibanya", categoria="cadenas", resumen="r"))
    assert cosa["jrTipo"] == "cosa" and cosa["jrNombreNorm"] == "coco ichibanya" and cosa["categoria"] == "cadenas"


def test_render_failure():
    html = render_failure(make_meta(description="caption <x>"), "transcripción", "JSON inválido")
    assert "caption &lt;x&gt;" in html and "transcripción" in html and "JSON inválido" in html
