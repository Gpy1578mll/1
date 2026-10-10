"""Structured person attributes and source locations shared by extraction and review."""
import datetime

FIELDS = ("фамилия", "имя", "отчество", "дата_рождения", "место_рождения")
SOURCES = ("фио", "дата_рождения", "место_рождения")
NULLABLE_STRING = {"type": ["string", "null"]}
PERSON_SCHEMA = {
    "type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {**{key: NULLABLE_STRING for key in FIELDS},
                       "исходные_фрагменты": {
                           "type": "object", "additionalProperties": False,
                           "properties": {key: NULLABLE_STRING for key in SOURCES},
                           "required": list(SOURCES)}},
        "required": [*FIELDS, "исходные_фрагменты"]}}

def validate_values(person):
    if not isinstance(person, dict) or set(person) != set(FIELDS):
        raise ValueError("Неверные поля сведений о человеке")
    for value in person.values():
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Неизвестное значение должно быть null, а не пустой строкой")
    date = person["дата_рождения"]
    if date and len(date) == 10 and date[2:3] == '.' and date[5:6] == '.':
        try:
            datetime.datetime.strptime(date, "%d.%m.%Y")
        except ValueError as exc:
            raise ValueError("Некорректная дата рождения") from exc

def person_label(person, fallback):
    name = " ".join(person[key] for key in FIELDS[:3] if person[key] is not None)
    return name or person["дата_рождения"] or person["место_рождения"] or fallback

def validate_spans(person, spans, text):
    validate_values(person)
    if not isinstance(spans, dict) or set(spans) != set(SOURCES):
        raise ValueError("Неверные исходные фрагменты человека")
    for field, span in spans.items():
        if span is None:
            values = [person[key] for key in FIELDS[:3]] if field == "фио" else [person[field]]
            if any(value is not None for value in values):
                raise ValueError("Для заполненного поля необходимо указать исходный фрагмент")
            continue
        if not isinstance(span, dict):
            raise ValueError("Неверные границы исходного фрагмента")
        start, end = span.get("start"), span.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
            raise ValueError("Границы исходного фрагмента вне текста")
    if not any(spans.values()):
        raise ValueError("Человек должен иметь хотя бы один исходный фрагмент")
    place = person["место_рождения"]
    if place is not None:
        span = spans["место_рождения"]
        if place != text[span["start"]:span["end"]]:
            raise ValueError("Место рождения должно точно совпадать с исходным фрагментом")

def parse_person(item, chunk, offset):
    if not isinstance(item, dict) or set(item) != {*FIELDS, "исходные_фрагменты"}:
        raise ValueError("Неверный объект человека")
    person = {field: item[field] for field in FIELDS}
    originals = item["исходные_фрагменты"]
    if not isinstance(originals, dict) or set(originals) != set(SOURCES):
        raise ValueError("Неверные исходные фрагменты человека")
    spans, notes = {}, []
    for field, original in originals.items():
        if original is None:
            spans[field] = None
            continue
        if not isinstance(original, str) or not original:
            raise ValueError("Исходный фрагмент должен быть строкой или null")
        position = chunk.find(original)
        if position < 0:
            raise ValueError("Выделенный моделью фрагмент отсутствует в исходном тексте")
        if chunk.find(original, position + 1) >= 0:
            notes.append(f"Фрагмент «{field}» встречается несколько раз: проверьте привязку")
        spans[field] = {"start": position, "end": position + len(original)}
    validate_spans(person, spans, chunk)
    anchor = next(span for span in spans.values() if span)
    original = chunk[anchor["start"]:anchor["end"]]
    return {"kind": "persons", "person": person,
            "source_spans": {field: {"start": span["start"] + offset, "end": span["end"] + offset}
                             if span else None for field, span in spans.items()},
            "start": anchor["start"] + offset, "end": anchor["end"] + offset,
            "original_text": original, "normalized_value": person_label(person, original),
            "note": "; ".join(notes)}
