"""Read BibTeX fields and preserve original entry spans for safe repairs."""

from calendar import month_name
from dataclasses import dataclass
import re

from latex import line_at


class BibError(ValueError):
    def __init__(self, position, message):
        super().__init__(message)
        self.position = position


@dataclass
class Entry:
    key: str
    kind: str
    fields: dict
    start: int
    end: int
    raw: str
    uses_macros: bool


class Reader:
    def __init__(self, text):
        self.text = text
        self.position = 0
        self.macros = {month[:3].lower(): month for month in month_name[1:]}
        self.problems = []
        self.uses_macros = False

    @property
    def char(self):
        return self.text[self.position:self.position + 1]

    def fail(self, message):
        raise BibError(self.position, message)

    def skip(self):
        while self.char:
            if self.char.isspace():
                self.position += 1
            elif self.char == "%":
                newline = self.text.find("\n", self.position)
                self.position = newline + 1 if newline >= 0 else len(self.text)
            else:
                break

    def take(self, pattern):
        match = re.compile(pattern).match(self.text, self.position)
        if not match:
            return ""
        self.position = match.end()
        return match[0]

    def expect(self, char):
        self.skip()
        if self.char != char:
            self.fail(f"Se esperaba {char}.")
        self.position += 1

    def delimited(self, opening, closing):
        start = self.position
        depth = braces = 0
        inner_open, inner_close = ("{", "}") if opening == '"' else (opening, closing)
        while self.char:
            char = self.char
            self.position += 1
            if char == "\\":
                self.position += 1
                continue
            if opening == "(":
                braces += (char == "{") - (char == "}")
            if not braces:
                if not depth and char == closing:
                    return self.text[start:self.position - 1]
                depth += (char == inner_open) - (char == inner_close)
            if depth < 0 or braces < 0:
                self.fail("Llave inesperada en un valor.")
        self.fail(f"Valor o entrada sin cierre (abierto en línea {line_at(self.text, start - 1)}).")

    def value(self):
        parts = []
        while True:
            self.skip()
            if self.char in {"{", '"'}:
                opening = self.char
                self.position += 1
                parts.append(self.delimited(opening, "}" if opening == "{" else '"'))
            else:
                start = self.position
                bare = self.take(r"[\w.:+/-]+")
                if not bare:
                    self.fail("Valor BibTeX inválido.")
                if not re.fullmatch(r"[0-9]+", bare):
                    self.uses_macros = True
                    if bare.lower() not in self.macros:
                        self.problems.append(BibError(start, f"Macro BibTeX sin definir: {bare}."))
                parts.append(self.macros.get(bare.lower(), bare))
            self.skip()
            if self.char != "#":
                return "".join(parts)
            self.position += 1

    def entry(self, start):
        kind = self.take(r"[a-zA-Z]+\b").lower()
        if not kind:
            self.fail("Tipo de entrada inválido.")
        self.skip()
        opening = self.char
        if opening not in {"{", "("}:
            self.fail("Se esperaba { o (.")
        closing = "}" if opening == "{" else ")"
        self.position += 1
        if kind == "comment":
            self.delimited(opening, closing)
            return None
        self.uses_macros = False
        if kind == "preamble":
            self.value()
            self.expect(closing)
            return None
        self.skip()
        if kind == "string":
            name = self.take(r"[a-zA-Z][\w.:-]*")
            if not name:
                self.fail("Nombre de macro inválido.")
            self.expect("=")
            expanded = self.value()
            if self.char == ",":
                self.position += 1
            self.expect(closing)
            self.macros[name.lower()] = expanded
            return None
        key = self.take(r"""[^\s,=(){}"%#@]+""")
        if not key:
            self.fail("Clave bibliográfica vacía o inválida.")
        self.skip()
        if self.char != closing:
            self.expect(",")
        fields = {}
        self.skip()
        while self.char != closing:
            field_start = self.position
            name = self.take(r"[a-zA-Z][\w-]*").lower()
            if not name:
                self.fail("Nombre de campo inválido o entrada sin cierre.")
            self.expect("=")
            expanded = self.value()
            if name in fields:
                self.problems.append(BibError(field_start, f"Campo {name} repetido en {key}."))
            else:
                fields[name] = expanded
            if self.char != closing:
                self.expect(",")
            self.skip()
        self.position += 1
        return Entry(key, kind, fields, start, self.position, self.text[start:self.position], self.uses_macros)


def parse_bib(text):
    reader = Reader(text)
    entries = []
    next_entry = re.compile(r"\n[ \t]*(@[a-zA-Z]+\s*[{(])")
    while reader.char:
        reader.skip()
        if reader.char != "@":
            if not reader.char:
                break
            if not reader.take(r"[^@%\r\n]+"):
                reader.position += 1
            continue
        start = reader.position
        reader.position += 1
        try:
            entry = reader.entry(start)
            if entry:
                entries.append(entry)
        except BibError as error:
            reader.problems.append(error)
            following = next_entry.search(text, start + 1)
            reader.position = following.start(1) if following else len(text)
    return entries, reader.problems
