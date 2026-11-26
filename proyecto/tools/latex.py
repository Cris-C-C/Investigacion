"""Lexical and structural checks for the supported LaTeX table subset."""

from dataclasses import dataclass, field
import re


CITES = {"cite", "citep", "citet", "citeauthor", "citeyear"}
TABLES = {"tabular", "tabular*", "longtable"}
SECTIONS = {"endfirsthead", "endhead", "endfoot", "endlastfoot"}
RULES = {"hline", "cline", "toprule", "midrule", "bottomrule", "cmidrule", "addlinespace"}
TEXT_GROUPS = {"textbf", "textit", "emph", "texttt", "textnormal", "textsc", "mbox"}
PROTECTED_GROUPS = CITES | {"label", "ref", "pageref", "url", "href", "includegraphics"}
COMMAND = re.compile(r"[a-zA-Z]+|[\s\S]")
COMMENT = re.compile(r"\\[\s\S]|%[^\r\n]*")


class LatexError(ValueError):
    def __init__(self, position, message):
        super().__init__(message)
        self.position = position


@dataclass
class Metadata:
    caption: str = ""
    captions: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    cites: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    problems: list = field(default_factory=list)


@dataclass
class Group:
    value: str
    start: int
    end: int


def line_at(text, position):
    return text.count("\n", 0, position) + 1


def strip_comments(text):
    return COMMENT.sub(lambda match: match[0] if match[0].startswith("\\") else " " * len(match[0]), text)


def command(text, position):
    match = COMMAND.match(text, position + 1)
    return (match[0], match.end()) if match else ("", position + 1)


def argument(text, position, opening="{", required=True):
    while position < len(text) and text[position].isspace():
        position += 1
    if text[position:position + 1] != opening:
        if required:
            raise LatexError(position, f"Se esperaba {opening}.")
        return None
    closing = {"{": "}", "[": "]", "(": ")"}[opening]
    start = position + 1
    position = start
    depth, braces = 1, 0
    while position < len(text):
        char = text[position]
        if char == "\\":
            _, position = command(text, position)
            continue
        if opening != "{":
            braces += (char == "{") - (char == "}")
        if not braces:
            depth += (char == opening) - (char == closing)
            if not depth:
                return Group(text[start:position], start, position + 1)
        position += 1
    raise LatexError(start - 1, f"Grupo {opening}{closing} sin cerrar.")


def optional_end(text, position, opening="["):
    group = argument(text, position, opening, required=False)
    return group.end if group else position


def star_end(text, position):
    return position + (text[position:position + 1] == "*")


def read_metadata(source):
    text = strip_comments(source)
    result = Metadata()
    position = 0
    while (position := text.find("\\", position)) >= 0:
        start = position
        name, position = command(text, start)
        try:
            if name in CITES:
                end = optional_end(text, optional_end(text, star_end(text, position)))
                group = argument(text, end)
                offset = group.start
                for candidate in group.value.split(","):
                    key = candidate.strip()
                    index = offset + len(candidate) - len(candidate.lstrip())
                    if not key or any(char.isspace() or char in "{}" for char in key):
                        result.problems.append(LatexError(index, "Clave de cita vacía o inválida."))
                    else:
                        result.cites.append((key, index))
                    offset += len(candidate) + 1
                position = group.end
            elif name in {"label", "ref", "pageref"}:
                group = argument(text, position)
                key = group.value.strip()
                if not key or any(char.isspace() or char in "{}" for char in key):
                    raise LatexError(start, f"Clave vacía o inválida en \\{name}.")
                (result.labels if name == "label" else result.refs).append((key, start))
                position = group.end
            elif name == "caption":
                end = optional_end(text, star_end(text, position))
                group = argument(text, end)
                result.captions.append((group.start, group.value))
                if not result.caption:
                    result.caption = group.value.strip()
        except LatexError as error:
            result.problems.append(error)
    return result


def find_table(text):
    braces, envs, tables, problems = [], [], [], []
    position = 0
    while position < len(text):
        char = text[position]
        if char == "{":
            braces.append(position)
        elif char == "}":
            if braces:
                braces.pop()
            else:
                problems.append(LatexError(position, "Llave de cierre sin apertura."))
        if char != "\\":
            position += 1
            continue
        index = position
        name, position = command(text, index)
        if name not in {"begin", "end"}:
            continue
        try:
            group = argument(text, position)
        except LatexError as error:
            problems.append(error)
            continue
        position = group.end
        env = group.value.strip()
        if name == "begin":
            if any(item[0] in TABLES for item in envs):
                problems.append(LatexError(index, f"Entorno anidado no admitido en la tabla: {env}."))
            envs.append((env, index, position))
        elif not envs or envs[-1][0] != env:
            expected = f" (se esperaba {envs[-1][0]})" if envs else ""
            problems.append(LatexError(index, f"\\end{{{env}}} no coincide con la apertura{expected}."))
        else:
            opened = envs.pop()
            if env in TABLES:
                tables.append((*opened, index))
    problems.extend(LatexError(index, "Llave de apertura sin cierre.") for index in braces)
    problems.extend(LatexError(index, f"Entorno sin cerrar: {env}.") for env, index, _ in envs)
    if len(tables) > 1:
        problems.append(LatexError(tables[1][1], "Usa un archivo .tex por tabla."))
    if not tables and not problems:
        problems.append(LatexError(0, "Se esperaba un entorno tabular o longtable."))
    return tables[0] if len(tables) == 1 else None, problems


def column_count(text, spec, nesting=0):
    position = spec.start
    count = 0
    while position < spec.end - 1:
        char = text[position]
        position += 1
        if char.isspace() or char == "|":
            continue
        if char in "@!><pmb":
            position = argument(text, position).end
            count += char in "pmb"
        elif char in "lcr":
            count += 1
        elif char == "*":
            repeat = argument(text, position)
            child = argument(text, repeat.end)
            times = repeat.value.strip()
            if nesting > 12 or not re.fullmatch(r"[0-9]{1,3}", times) or not 1 <= int(times) <= 256:
                raise LatexError(repeat.start, "Repetición de columnas fuera de rango.")
            count += int(times) * column_count(text, child, nesting + 1)
            position = child.end
        else:
            raise LatexError(position - 1, f"Columna no admitida: {char}.")
    if not 1 <= count <= 256:
        raise LatexError(spec.start, "Se requieren entre 1 y 256 columnas.")
    return count


def math_opener(text, position):
    if text[position:position + 1] == "$":
        return "$$" if text.startswith("$$", position) else "$"
    if text.startswith((r"\(", r"\["), position):
        return text[position:position + 2]
    return ""


def math_end(text, position, opening, stop=None):
    closing = {r"\(": r"\)", r"\[": r"\]"}.get(opening, opening)
    index = position + len(opening)
    stop = len(text) if stop is None else stop
    while index < stop:
        if text.startswith(closing, index, stop):
            return index + len(closing)
        if text[index] == "\\":
            _, index = command(text, index)
        else:
            index += 1
    raise LatexError(position, "Expresión matemática sin cerrar.")


def scan_rows(text, start, end):
    chunks, problems = {}, []
    rows, cells = [], []
    depth = 0
    position = field_start = start
    metadata_row = False

    def add_cell(stop):
        value = text[field_start:stop]
        cells.append((field_start + len(value) - len(value.lstrip()), value.strip()))

    def finish(stop, explicit=False):
        if cells or text[field_start:stop].strip() or (explicit and not metadata_row):
            add_cell(stop)
            rows.append(cells.copy())
            cells.clear()

    while position < end:
        index = position
        char = text[position]
        opening = math_opener(text, position)
        if opening:
            position = math_end(text, position, opening, end)
            continue
        position += 1
        depth += (char == "{") - (char == "}")
        if char == "&" and depth == 0:
            add_cell(index)
            field_start = position
        if char != "\\":
            continue
        name, position = command(text, index)
        if depth:
            continue
        if name in {"\\", "tabularnewline", "cr"}:
            finish(index, explicit=True)
            metadata_row = False
            position = field_start = optional_end(text, star_end(text, position))
        elif name in RULES | SECTIONS | {"caption"} or (
                name == "label" and not (cells or text[field_start:index].strip())):
            if cells or text[field_start:index].strip():
                problems.append(LatexError(index, fr"Falta \\ antes de \{name}."))
                finish(index)
            if name in SECTIONS:
                if name in chunks:
                    problems.append(LatexError(index, "Sección de longtable repetida."))
                chunks[name] = rows
                rows = []
            elif name in {"caption", "label"}:
                position = argument(text, optional_end(text, star_end(text, position))).end
                metadata_row = True
            elif name != "hline":
                position = optional_end(text, position)
                if name in {"cline", "cmidrule"}:
                    position = argument(text, optional_end(text, position, "(")).end
            field_start = position
    finish(end)
    return rows, chunks, problems


def cell_span(text, position, value):
    width = height = 1
    while re.match(r"\\(?:multicolumn|multirow)\b", value):
        name, end = command(text, position)
        size = argument(text, optional_end(text, end))
        multirow = name == "multirow"
        spec = argument(text, optional_end(text, size.end) if multirow else size.end)
        inner = argument(text, optional_end(text, spec.end) if multirow else spec.end)
        end = position + len(value)
        number = size.value.strip()
        if (not re.fullmatch(r"[0-9]{1,5}", number) or not 1 <= int(number) <= 65534
                or inner.end > end or text[inner.end:end].strip()):
            raise LatexError(position, "Extensión de celda no válida.")
        if multirow:
            height = int(number)
        else:
            width = int(number)
            if column_count(text, spec) != 1:
                raise LatexError(spec.start, "multicolumn requiere una sola alineación.")
        value = inner.value.strip()
        position = inner.start + len(inner.value) - len(inner.value.lstrip())
    return width, height


def row_problems(text, rows, columns):
    occupied = [0] * columns
    problems = []
    for row_index, cells in enumerate(rows):
        column = 0
        previous_occupancy = occupied.copy()
        try:
            for position, value in cells:
                if column >= columns:
                    raise LatexError(position, "Demasiadas celdas. Revisa los separadores &.")
                if occupied[column] > row_index:
                    if value:
                        raise LatexError(position, "Se esperaba una celda vacía bajo multirow.")
                    column += 1
                    continue
                width, height = cell_span(text, position, value)
                if column + width > columns or any(used > row_index for used in occupied[column:column + width]):
                    raise LatexError(position, "multicolumn excede el ancho o se superpone con multirow.")
                if row_index + height > len(rows):
                    raise LatexError(position, "multirow excede las filas disponibles.")
                occupied[column:column + width] = [row_index + height] * width
                column += width
            if column != columns:
                raise LatexError(cells[0][0], fr"Fila con {column} de {columns} columnas. Revisa & y \\.")
        except LatexError as error:
            occupied = previous_occupancy
            problems.append(error)
    return problems


def special_characters(text, cells):
    """Find unescaped text symbols, ignoring math and opaque macro arguments."""
    found = set()

    def visit(start, stop, grouped=False):
        position = start
        while position < stop:
            char = text[position]
            opening = math_opener(text, position)
            if opening:
                position = math_end(text, position, opening, stop)
                continue
            if char == "\\":
                name, position = command(text, position)
                if name in PROTECTED_GROUPS:
                    position = optional_end(text, optional_end(text, star_end(text, position)))
                    group = argument(text, position, required=False)
                    if group:
                        position = group.end
                    if name == "href":
                        group = argument(text, position, required=False)
                        if group:
                            visit(group.start, group.end - 1, True)
                            position = group.end
                elif name in {"multicolumn", "multirow"}:
                    size = argument(text, optional_end(text, position), required=False)
                    if size:
                        setting_start = optional_end(text, size.end) if name == "multirow" else size.end
                        setting = argument(text, setting_start)
                        value_start = optional_end(text, setting.end) if name == "multirow" else setting.end
                        value = argument(text, value_start)
                        visit(value.start, value.end - 1, True)
                        position = value.end
                elif name in TEXT_GROUPS:
                    group = argument(text, position)
                    visit(group.start, group.end - 1, True)
                    position = group.end
                else:
                    # Macro arguments and dimensions can contain intentional special characters.
                    group = argument(text, position, required=False)
                    while group and group.end <= stop:
                        position = group.end
                        group = argument(text, position, required=False)
                continue
            if char == "{":
                group = argument(text, position)
                visit(group.start, group.end - 1, True)
                position = group.end
                continue
            if char in "_#^" or (grouped and char == "&"):
                found.add(position)
            position += 1

    for position, value in cells:
        visit(position, position + len(value))
    return sorted(found)


def inspect_table(source):
    """Return structural errors and positions of unescaped text symbols."""
    text = strip_comments(source)
    table, problems = find_table(text)
    if not table or problems:
        return problems, []
    name, _, start, end = table
    try:
        if name == "tabular*":
            start = argument(text, start).end
        spec = argument(text, optional_end(text, start))
        columns = column_count(text, spec)
        rows, chunks, row_errors = scan_rows(text, spec.end, end)
        problems.extend(row_errors)
        if name != "longtable" and chunks:
            problems.append(LatexError(start, "Secciones reservadas para longtable."))
        head = chunks.get("endfirsthead", chunks.get("endhead", []))
        foot = chunks.get("endlastfoot", chunks.get("endfoot", []))
        display_rows = head + rows + foot
        if not display_rows:
            problems.append(LatexError(spec.end, "La tabla no tiene filas."))
        problems.extend(row_problems(text, display_rows, columns))
        for chunk in chunks.values():
            if chunk is not head and chunk is not foot:
                problems.extend(row_problems(text, chunk, columns))
        cells = [cell for row in display_rows for cell in row]
        cells.extend(cell for chunk in chunks.values() if chunk is not head and chunk is not foot
                     for row in chunk for cell in row)
        cells.extend(read_metadata(source).captions)
        return problems, special_characters(text, cells)
    except LatexError as error:
        problems.append(error)
        return problems, []


def percent_candidates(text):
    """Distinguish ordinary comments from likely accidental numeric percentages."""
    return [match.start() for match in COMMENT.finditer(text)
            if match[0].startswith("%") and match.start() and text[match.start() - 1].isdigit()
            and re.match(r"%[ \t]*(?:&|\\\\|})", match[0])]
