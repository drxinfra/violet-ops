#!/usr/bin/env python3
"""Violet Ops — тёмная тема VS Code для DevOps-кода: Ansible, Jinja, Helm, Jenkins, Shell, Go, Python, SQL.

Генерирует варианты темы, проверяет контраст (WCAG 2 и APCA) и различимость соседних ролей (ΔE в OKLab),
собирает .vsix через @vscode/vsce и рендерит превью образцов тем же движком подсветки, что у VS Code.

    python3 -I build.py                 # темы + .vsix + превью (preview/*.png)
    python3 -I build.py --no-preview    # без превью
    code --install-extension violet-ops-<версия>.vsix

Превью требует Node.js, Google Chrome и установленные расширения VS Code с грамматиками
(redhat.ansible, ms-kubernetes-tools.vscode-kubernetes-tools), см. README.
"""
import json, math, pathlib, shutil, subprocess, sys

ROOT = pathlib.Path(__file__).parent
EXT = ROOT / "extension"
RENDER = ROOT / "render"
PREVIEW = ROOT / "preview"
SYNTAXES = ROOT / "syntaxes"
VERSION = "1.0.0"


# --- цветовая математика: OKLab/OKLCH, WCAG 2, APCA --------------------------------
def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def oklab(h):
    r, g, b = (_lin(c) for c in rgb(h))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def from_oklab(L, a, b):
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    rgb_ = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    return "#" + "".join(f"{round(min(1, max(0, _unlin(min(1, max(0, c))))) * 255):02X}" for c in rgb_)


def oklch(h):
    L, a, b = oklab(h)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def from_oklch(L, C, H):
    return from_oklab(L, C * math.cos(math.radians(H)), C * math.sin(math.radians(H)))


def mix(a, b, t):
    """Смесь в OKLab: t=0 → a, t=1 → b. В sRGB смеси с акцентом раздувают хрому."""
    p, q = oklab(a), oklab(b)
    return from_oklab(*(x + (y - x) * t for x, y in zip(p, q)))


def wcag(a, b):
    Y = lambda h: sum(k * _lin(c) for k, c in zip((0.2126, 0.7152, 0.0722), rgb(h)))
    la, lb = sorted((Y(a), Y(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def apca(txt, bg):
    """APCA-W3 0.0.98G: |Lc| ≥ 60 — обычный текст кода, ≥ 45 — второстепенное."""
    Y = lambda h: sum(k * c ** 2.4 for k, c in zip((0.2126729, 0.7151522, 0.0721750), rgb(h)))
    clamp = lambda y: y if y > 0.022 else y + (0.022 - y) ** 1.414
    yt, yb = clamp(Y(txt)), clamp(Y(bg))
    if abs(yb - yt) < 0.0005:
        return 0.0
    if yb > yt:
        s = (yb ** 0.56 - yt ** 0.57) * 1.14
        return 0.0 if s < 0.1 else (s - 0.027) * 100
    s = (yb ** 0.65 - yt ** 0.62) * 1.14
    return 0.0 if s > -0.1 else (s + 0.027) * 100


def delta_e(a, b):
    return math.dist(oklab(a), oklab(b))


# --- палитра --------------------------------------------------------------------
# Подобрана перебором в OKLCH: код ≥ 7.5:1 и |Lc| ≥ 60, соседние роли разведены на ΔE ≥ 0.098.
BASE = dict(
    FG="#F4F3FF",      # текст интерфейса: почти белый, на светлом сероватом фоне текст «затуманивается»
    FG_DIM="#A4A2C6",  # пунктуация, операторы, «:» — тише смысловых ролей
    COMMENT="#9897CC",  # комментарии, курсив: 6:1
    ACCENT="#8C7BFF",  # акцент интерфейса
    VIOLET="#C5B9FF",  # ключевые слова: when/loop/register, if/for/def/func
    PINK="#FF85D4",    # модуль ansible (жирный)
    AZURE="#6BC3FE",   # ключи YAML и функции (в одном файле почти не встречаются)
    CYAN="#52F0FF",    # параметры модуля, поля и свойства, опции команд
    TEAL="#1BD7BE",    # фильтры jinja, функции sprig/helm, пакеты, regexp
    GREEN="#90E9A3",   # строки
    YELLOW="#E4CE63",  # переменные внутри шаблонов: {{ var }}, .Values, $VAR, ${...}, env.X
    ORANGE="#F6A322",  # числа, true/false, null, константы
    GOLD="#FBD6B5",    # типы и классы, заголовки ## в markdown
    CORAL="#FFAA90",   # аргументы функций, именованные аргументы, self (курсив)
    RED="#FF8993",     # ошибки
)
# Основная палитра: роли разнесены по всему цветовому кругу и насыщенные.
VIVID = dict(BASE,
    VIVID=True,         # признак яркой палитры: {{ }} полным розовым
    CODE_FG="#D9D9DF",  # обычный текст кода: мягче белого интерфейса, чтобы не перетягивал цветные роли
    FG_DIM="#B7B5DD",
    VIOLET="#B897FF",   # ключевые слова, name/when/loop/register — насыщеннее, чтобы не сливаться с текстом
    PINK="#FF7ED0",     # модуль ansible, {{ }} и {% %}
    AZURE="#7AB4FF",    # ключи YAML / переменные в vars и defaults — синие, не бирюзовые
    CYAN="#52F0FF",     # параметры модуля
    TEAL="#36E8B8",     # фильтры jinja, sprig, пакеты
    GREEN="#A8F38C",    # строки — салатовые, дальше от бирюзового
    YELLOW="#FFDE59",   # переменные в {{ }}, .Values, $VAR
    ORANGE="#FFB13B",   # числа, булевы — янтарный, чтобы не путать с коралловым
    GOLD="#FFC978",     # типы
    CORAL="#FFAA90",    # аргументы
)
BRACKETS = ("#FFD84A", "#E57BFF", "#3FA9FF")   # пары скобок по уровню вложенности
ROLE_KEYS = ["VIOLET", "PINK", "AZURE", "CYAN", "TEAL", "GREEN", "YELLOW", "ORANGE", "GOLD", "CORAL"]


def derive(p):
    p = dict(p)
    p.setdefault("CODE_FG", p["FG"])
    L, C, h = oklch(p["PINK"])
    # {{ }} и {% %}: в яркой палитре полным розовым (без жирного), в спокойной — тише модуля
    p["PINK_DIM"] = p["PINK"] if p.get("VIVID") else from_oklch(L, C * 0.62, h)
    return p


def soften(p):
    """Вечерний вариант: текст мягче, хрома ролей −15 %, светлота прежняя."""
    q = dict(p)
    q["FG"] = "#E6E4F7"
    for k in ROLE_KEYS + ["RED"]:
        L, C, h = oklch(p[k])
        q[k] = from_oklch(L, C * 0.85, h)
    return q


# --- фоны (OKLCH): редактор, боковая панель, самый тёмный, строка курсора -----------
def bg_set(L, C, h):
    return dict(bg=from_oklch(L, C, h), side=from_oklch(L - 0.022, C * 0.87, h),
                deep=from_oklch(L - 0.042, C * 0.71, h), line=from_oklch(L + 0.058, C * 1.25, h))


VARIANTS = {
    # основная — яркая палитра; Graphite — она же на нейтральном фоне; Calm — приглушённая палитра BASE
    "violet":   dict(name="Violet Ops",          bgs=bg_set(0.200, 0.024, 285), pal=derive(VIVID), vivid=True),
    "graphite": dict(name="Violet Ops Graphite", bgs=bg_set(0.200, 0.010, 285), pal=derive(VIVID), vivid=True),
    "calm":     dict(name="Violet Ops Calm",     bgs=bg_set(0.200, 0.024, 285), pal=derive(BASE)),
}
DEFAULT = "violet"


def tc(scope, fg, style=None):
    s = {"foreground": fg}
    if style is not None:
        s["fontStyle"] = style
    return {"scope": scope if isinstance(scope, list) else [scope], "settings": s}


def token_colors(p):
    FG, FG_DIM, COMMENT = p.get("CODE_FG", p["FG"]), p["FG_DIM"], p["COMMENT"]
    VIOLET, PINK, PINK_DIM, AZURE, CYAN = p["VIOLET"], p["PINK"], p["PINK_DIM"], p["AZURE"], p["CYAN"]
    TEAL, GREEN, YELLOW, ORANGE, GOLD, CORAL, RED = (p[k] for k in
                                                     ("TEAL", "GREEN", "YELLOW", "ORANGE", "GOLD", "CORAL", "RED"))
    return [
        # --- общее -------------------------------------------------------------
        tc(["comment", "punctuation.definition.comment", "comment.block.gotpl",
            "comment.line.number-sign.yaml"], COMMENT, "italic"),
        tc(["string", "string.quoted", "string.unquoted.block.yaml", "string.unquoted-block",
            "string.template"], GREEN),
        tc(["string.unquoted.plain.out.yaml", "string.unquoted.plain.in.yaml", "string.unquoted"], FG),
        tc(["string.regexp", "string.regexp.compiled"], TEAL),
        tc(["constant.numeric", "constant.language", "constant.other.timestamp.yaml",
            "constant.language.boolean.yaml", "constant.language.null.yaml", "support.constant",
            "variable.other.constant", "constant.other.groovy"], ORANGE),
        tc(["constant.character.escape", "constant.other.placeholder",
            "constant.character.format.placeholder"], ORANGE),
        tc(["keyword", "keyword.control", "storage.type", "storage.modifier", "storage.type.def",
            "keyword.other.import", "keyword.other.package", "keyword.function", "keyword.type",
            "storage.type.function", "keyword.control.import", "keyword.control.from"], VIOLET),
        tc(["keyword.operator", "punctuation.separator.key-value", "punctuation.separator.key-value.mapping",
            "punctuation.separator.key-value.mapping.yaml", "punctuation.separator.mapping.yaml",
            "punctuation.separator.sequence.yaml"], FG_DIM),
        tc(["keyword.operator.logical", "keyword.operator.comparison", "keyword.operator.elvis",
            "keyword.operator.safe-navigation", "keyword.operator.word",
            "keyword.operator.logical.python", "keyword.operator.expression"], VIOLET),
        tc(["entity.name.function", "support.function", "meta.function-call.generic",
            "support.function.builtin", "support.function.print", "meta.method-call entity.name.function",
            "entity.name.function.member"], AZURE),
        tc(["entity.name.type", "entity.name.class", "entity.name.type.class", "support.type",
            "support.class", "entity.other.inherited-class", "storage.type.class",
            "support.type.python", "support.type.builtin", "entity.name.type.go",
            "storage.type.numeric.go", "storage.type.string.go", "storage.type.boolean.go",
            "storage.type.error.go", "storage.type.byte.go", "storage.type.rune.go",
            "storage.type.groovy", "storage.type.primitive.groovy", "storage.type.generic.groovy",
            "storage.type.object.array.groovy", "storage.type.sql"], GOLD),
        tc(["storage.type.def.groovy"], VIOLET),
        tc(["entity.name.namespace", "entity.name.package", "entity.name.import.go",
            "entity.name.package.go"], TEAL),
        tc(["storage.type.annotation", "meta.declaration.annotation", "meta.decorator",
            "entity.name.function.decorator", "punctuation.decorator"], GOLD),
        tc(["variable", "variable.other", "variable.other.readwrite"], FG),
        tc(["variable.parameter", "variable.parameter.method", "meta.closure.parameter",
            "variable.parameter.function.language.python"], CORAL, "italic"),
        tc(["variable.language", "variable.language.self", "variable.language.this",
            "variable.parameter.function.language.special.self.python"], CORAL, "italic"),
        tc(["variable.other.property", "variable.other.member", "meta.property", "support.variable.property",
            "variable.other.object.property", "entity.other.attribute-name"], CYAN),
        tc(["punctuation", "meta.brace"], FG_DIM),
        tc(["invalid", "invalid.illegal"], RED, "underline"),

        # --- YAML ---------------------------------------------------------------
        tc(["entity.name.tag.yaml", "entity.name.tag", "meta.flow-pair.key.yaml"], AZURE),
        tc(["punctuation.definition.block.sequence.item", "punctuation.definition.block.sequence.item.yaml"],
           VIOLET),
        tc(["entity.name.type.anchor.yaml", "variable.other.alias.yaml", "punctuation.definition.anchor.yaml",
            "punctuation.definition.alias.yaml", "keyword.control.flow.alias.yaml",
            "keyword.control.property.anchor.yaml"], ORANGE, "italic"),
        tc(["storage.type.tag-handle.yaml", "keyword.other.directive.yaml", "entity.other.document.begin.yaml",
            "entity.other.document.end.yaml"], FG_DIM),
        tc(["keyword.control.flow.block-scalar.literal", "keyword.control.flow.block-scalar.folded",
            "storage.modifier.chomping-indicator", "support.other.chomping-indicator.yaml",
            "punctuation.definition.block.scalar.literal.yaml",
            "punctuation.definition.block.scalar.folded.yaml"], VIOLET),

        # --- Ansible + Jinja ------------------------------------------------------
        tc(["entity.other.jinja.delimiter.variable", "entity.other.jinja.delimiter.tag",
            "punctuation.section.embedded.begin", "punctuation.section.embedded.end",
            "punctuation.definition.tag.jinja", "punctuation.section.tag.jinja",
            "punctuation.section.variable.jinja", "punctuation.definition.tag.begin.jinja",
            "punctuation.definition.tag.end.jinja"], PINK_DIM),
        tc(["entity.other.jinja.delimiter.comment"], COMMENT),
        tc(["meta.embedded.inline", "meta.scope.jinja.variable", "meta.scope.jinja.tag",
            "source.ansible-jinja variable.other", "variable.other.jinja", "variable.other.jinja.block",
            "meta.embedded.inline variable.other"], YELLOW),
        tc(["entity.name.function.filter", "entity.name.function.test", "support.function.filter.jinja",
            "entity.name.function.jinja", "meta.embedded.inline entity.name.function"], TEAL),
        tc(["source.ansible-jinja keyword.control", "keyword.control.jinja", "keyword.other.ansible",
            "meta.embedded.inline keyword.control"], VIOLET),
        tc(["source.ansible-jinja variable.other.property", "meta.embedded.inline variable.other.property"], CYAN),
        tc(["source.ansible-jinja string", "meta.embedded.inline string"], GREEN),
        tc(["source.ansible-jinja constant.numeric", "meta.embedded.inline constant"], ORANGE),
        tc(["keyword.other.special-method"], VIOLET),

        # --- Helm / Go-шаблоны -----------------------------------------------------
        # всё выражение {{ … }} размечено meta.tag.gotpl.instruction: без жирного, базовый цвет — функции
        tc(["meta.tag.gotpl.instruction"], TEAL),
        tc(["punctuation.definition.mapping.begin.helm", "punctuation.definition.mapping.end.helm"], PINK_DIM),
        tc(["keyword.control.helm", "source.helm keyword.control", "keyword.control.go-template"], VIOLET),
        tc(["support.function.sprig", "source.helm support.function", "support.function.go-template"], TEAL),
        tc(["variable.other.userVariable", "punctuation.definition.variable.userVariable",
            "variable.other.go-template", "constant.other.value", "keyword.operator.this",
            "source.helm variable.other.property"], YELLOW),
        tc(["source.helm keyword.operator.pipe", "meta.tag.gotpl.instruction keyword.operator.pipe",
            "meta.tag.gotpl.instruction keyword.operator.assignment"], FG_DIM),

        # --- Groovy / Jenkinsfile --------------------------------------------------
        tc(["variable.other.interpolated", "source.groovy.embedded.source",
            "punctuation.section.embedded.groovy"], YELLOW),
        tc(["constant.other.key"], CORAL, "italic"),   # именованные аргументы: sh(script: ..., returnStatus: ...)
        tc(["meta.method-call.groovy meta.method"], AZURE),
        tc(["meta.definition.method.signature.java entity.name.function.java",
            "meta.definition.method.groovy entity.name.function"], AZURE, "bold"),
        tc(["keyword.control.jenkins.groovy"], VIOLET),           # pipeline/stages/steps/post (своя грамматика)
        tc(["support.function.jenkins.groovy"], AZURE),           # sh/checkout/withCredentials/...
        tc(["variable.language.jenkins.groovy"], YELLOW),         # env./params./currentBuild.

        # --- Shell -----------------------------------------------------------------
        tc(["variable.other.normal.shell", "variable.other.positional.shell", "variable.other.special.shell",
            "punctuation.definition.variable.shell", "variable.other.bracket.shell",
            "variable.other.assignment.shell", "punctuation.section.expansion.parameter.shell"], YELLOW),
        tc(["support.function.builtin.shell", "entity.name.command.shell", "entity.name.function.call.shell"],
           AZURE),
        tc(["constant.other.option", "constant.other.option.dash.shell"], CYAN),
        tc(["string.interpolated.dollar.shell", "punctuation.definition.evaluation.backticks.shell",
            "string.interpolated.backtick.shell"], TEAL),
        tc(["keyword.operator.pipe.shell", "keyword.operator.logical.shell", "keyword.operator.redirect.shell",
            "keyword.operator.list.shell"], VIOLET),
        tc(["constant.character.escape.line-continuation.shell"], FG_DIM),

        # --- SQL, Dockerfile, ini/toml, json ---------------------------------------
        tc(["keyword.other.DML.sql", "keyword.other.sql", "keyword.other.DDL.create.II.sql",
            "keyword.other.data-integrity.sql"], VIOLET),
        tc(["constant.other.database-name.sql"], AZURE),          # алиас таблицы: dh.
        tc(["constant.other.table-name.sql"], CYAN),              # колонка: .historydate
        tc(["text.variable", "variable.other.sql", "variable.parameter.sql"], YELLOW),   # @startDate
        tc(["keyword.other.special-method.dockerfile", "keyword.control.dockerfile"], VIOLET),
        tc(["entity.name.section.group-title.ini", "support.type.property-name.toml",
            "keyword.other.definition.ini"], AZURE),
        tc(["support.type.property-name.json", "support.type.property-name"], AZURE),

        # --- Markdown: README и Changelog -------------------------------------------
        tc(["heading.1.markdown entity.name.section.markdown", "markup.heading.setext.1.markdown"], VIOLET, "bold"),
        tc(["heading.2.markdown entity.name.section.markdown", "markup.heading.setext.2.markdown"], GOLD, "bold"),
        tc(["heading.3.markdown entity.name.section.markdown"], CYAN, "bold"),
        tc(["heading.4.markdown entity.name.section.markdown", "heading.5.markdown entity.name.section.markdown",
            "heading.6.markdown entity.name.section.markdown"], TEAL, "bold"),
        tc(["markup.heading", "entity.name.section.markdown"], VIOLET, "bold"),
        tc(["punctuation.definition.heading.markdown"], COMMENT),
        tc(["markup.bold", "markup.bold punctuation"], "#FFFFFF", "bold"),
        tc(["markup.italic"], FG, "italic"),
        tc(["markup.inline.raw", "markup.inline.raw.string.markdown", "markup.raw"], GREEN),
        tc(["markup.fenced_code.block.markdown punctuation.definition.markdown",
            "fenced_code.block.language"], COMMENT),
        tc(["markup.underline.link", "string.other.link", "markup.underline.link.markdown"], AZURE),
        tc(["string.other.link.title.markdown", "string.other.link.description.markdown"], AZURE, "underline"),
        tc(["markup.list punctuation.definition.list.begin", "punctuation.definition.list.begin.markdown"],
           FG_DIM),
        tc(["markup.quote", "markup.quote.markdown"], FG_DIM, "italic"),
        tc(["meta.separator.markdown"], COMMENT),
        tc(["markup.table", "punctuation.separator.table.markdown"], FG_DIM),
        tc(["markup.inserted"], GREEN), tc(["markup.deleted"], RED), tc(["markup.changed"], ORANGE),
    ]


def semantic(p):
    return {
        # ansible language server — только в файлах ansible: модуль = class, параметр модуля = method,
        # ключ задачи (name/when/register/loop) = keyword, прочие ключи = property
        "class:ansible": {"foreground": p["PINK"], "bold": True},
        "method:ansible": p["CYAN"],
        "keyword:ansible": {"foreground": p["VIOLET"], "bold": True},
        "property:ansible": p["AZURE"],
        # остальные языки (Pylance, gopls, C#)
        "class": p["GOLD"], "class.declaration": {"foreground": p["GOLD"], "bold": True},
        "method": p["AZURE"], "property": p["CYAN"], "keyword": p["VIOLET"],
        "function": p["AZURE"], "function.defaultLibrary": p["AZURE"],
        "method.declaration": {"foreground": p["AZURE"], "bold": True},
        "function.declaration": {"foreground": p["AZURE"], "bold": True},
        "type": p["GOLD"], "interface": p["GOLD"], "struct": p["GOLD"], "enum": p["GOLD"],
        "typeParameter": p["GOLD"], "type.defaultLibrary": p["GOLD"],
        "namespace": p["TEAL"],
        "enumMember": p["ORANGE"],
        "parameter": {"foreground": p["CORAL"], "italic": True},
        "variable": p.get("CODE_FG", p["FG"]),
        "variable.readonly": p["ORANGE"],
        "variable.defaultLibrary": p["CORAL"],
        "selfParameter": {"foreground": p["CORAL"], "italic": True},
        "decorator": p["GOLD"], "macro": p["GOLD"],
        "string": p["GREEN"], "number": p["ORANGE"], "regexp": p["TEAL"],
        "label": p["AZURE"],
        "field": p["CYAN"],
    }


def ui_colors(b, p):
    """Цвета интерфейса от фона: смеси в OKLab с малыми долями акцента."""
    BG, SIDE, DEEP, LINE = b["bg"], b["side"], b["deep"], b["line"]
    FG, FG_DIM, COMMENT, ACC = p["FG"], p["FG_DIM"], p["COMMENT"], p["ACCENT"]
    ORANGE, RED, PINK = p["ORANGE"], p["RED"], p["PINK"]
    HOVER = mix(BG, ACC, 0.10)
    BORDER = mix(BG, ACC, 0.08)
    SURFACE = mix(BG, ACC, 0.05)          # поля ввода, блоки кода в hover
    SEL = mix(BG, ACC, 0.30)              # выделенный элемент списка
    SEL_IN = mix(BG, ACC, 0.16)
    B1, B2, B3 = BRACKETS
    return {
        "focusBorder": ACC + "AA", "foreground": FG, "descriptionForeground": mix(FG_DIM, FG, 0.35),
        "errorForeground": RED, "icon.foreground": "#ECEAFF", "selection.background": ACC + "66",
        "widget.border": BORDER, "sash.hoverBorder": ACC,

        "editor.background": BG, "editor.foreground": p.get("CODE_FG", FG),
        "editorLineNumber.foreground": mix(BG, COMMENT, 0.8), "editorLineNumber.activeForeground": "#E6E4FF",
        "editor.lineHighlightBackground": LINE, "editor.lineHighlightBorder": "#00000000",
        "editor.selectionBackground": ACC + "66", "editor.inactiveSelectionBackground": ACC + "40",
        "editor.selectionHighlightBackground": ACC + "1F", "editor.selectionHighlightBorder": ACC + "55",
        "editor.wordHighlightBackground": ACC + "1A", "editor.wordHighlightTextBackground": ACC + "1A",
        "editor.wordHighlightStrongBackground": ORANGE + "1F",
        "editor.findMatchBackground": ORANGE + "40", "editor.findMatchHighlightBackground": ORANGE + "22",
        "editor.findMatchBorder": ORANGE,
        "editorCursor.foreground": "#FFFFFF",
        "editorWhitespace.foreground": mix(BG, COMMENT, 0.35),
        "editorIndentGuide.background1": mix(BG, COMMENT, 0.35),
        "editorIndentGuide.activeBackground1": mix(BG, ACC, 0.6),
        "editorRuler.foreground": mix(BG, COMMENT, 0.25),
        "editorBracketMatch.background": ACC + "33", "editorBracketMatch.border": ACC + "AA",
        "editorBracketHighlight.foreground1": B1, "editorBracketHighlight.foreground2": B2,
        "editorBracketHighlight.foreground3": B3, "editorBracketHighlight.foreground4": B1,
        "editorBracketHighlight.foreground5": B2, "editorBracketHighlight.foreground6": B3,
        "editorBracketHighlight.unexpectedBracket.foreground": RED,
        "editorBracketPairGuide.activeBackground1": B1 + "80",
        "editorBracketPairGuide.activeBackground2": B2 + "80",
        "editorBracketPairGuide.activeBackground3": B3 + "80",
        "editorGutter.addedBackground": "#7EE07A", "editorGutter.modifiedBackground": p["AZURE"],
        "editorGutter.deletedBackground": RED,
        "editorError.foreground": RED, "editorWarning.foreground": ORANGE, "editorInfo.foreground": p["AZURE"],
        "editorHint.foreground": p["TEAL"],
        "editorWidget.background": SIDE, "editorWidget.border": BORDER,
        "editorSuggestWidget.background": SIDE, "editorSuggestWidget.border": BORDER,
        "editorSuggestWidget.selectedBackground": SEL_IN, "editorSuggestWidget.highlightForeground": p["CYAN"],
        "editorHoverWidget.background": SIDE, "editorHoverWidget.border": BORDER,
        "editorOverviewRuler.border": "#00000000",
        "editorStickyScroll.background": BG, "editorStickyScrollHover.background": HOVER,
        "editorInlayHint.foreground": mix(COMMENT, FG, 0.25), "editorInlayHint.background": SURFACE,
        "editorCodeLens.foreground": COMMENT,
        "editorGhostText.foreground": mix(BG, COMMENT, 0.8),
        "minimap.background": BG, "minimapSlider.background": ACC + "22",
        "scrollbarSlider.background": ACC + "26", "scrollbarSlider.hoverBackground": ACC + "44",
        "scrollbarSlider.activeBackground": ACC + "66",

        "editorGroupHeader.tabsBackground": SIDE, "editorGroup.border": BORDER,
        "tab.activeBackground": BG, "tab.activeForeground": "#FFFFFF", "tab.activeBorderTop": ACC,
        "tab.inactiveBackground": SIDE, "tab.inactiveForeground": mix(SIDE, FG, 0.72), "tab.border": DEEP,
        "tab.hoverBackground": HOVER, "tab.unfocusedActiveBorderTop": ACC + "66",
        "tab.unfocusedActiveForeground": mix(SIDE, FG, 0.85), "tab.unfocusedInactiveForeground": mix(SIDE, FG, 0.5),
        "breadcrumb.foreground": mix(FG_DIM, FG, 0.35), "breadcrumb.focusForeground": FG,

        "activityBar.background": DEEP, "activityBar.foreground": "#F4F3FF",
        "activityBar.inactiveForeground": mix(DEEP, FG, 0.45), "activityBar.activeBorder": ACC,
        "activityBarBadge.background": "#6E5CFF", "activityBarBadge.foreground": "#FFFFFF",
        "sideBar.background": SIDE, "sideBar.foreground": mix(SIDE, FG, 0.94), "sideBar.border": BORDER,
        "sideBarTitle.foreground": "#F4F3FF", "sideBarSectionHeader.background": SIDE,
        "sideBarSectionHeader.foreground": "#F4F3FF", "sideBarSectionHeader.border": BORDER,
        "list.activeSelectionBackground": SEL, "list.activeSelectionForeground": "#FFFFFF",
        "list.inactiveSelectionBackground": SEL_IN, "list.hoverBackground": HOVER,
        "list.focusOutline": ACC + "AA", "list.highlightForeground": p["CYAN"],
        "tree.indentGuidesStroke": mix(SIDE, ACC, 0.35),
        "badge.background": "#6E5CFF", "badge.foreground": "#FFFFFF",

        "statusBar.background": SIDE, "statusBar.foreground": mix(SIDE, FG, 0.94), "statusBar.border": BORDER,
        "statusBar.noFolderBackground": SIDE, "statusBar.debuggingBackground": "#6E3CC0",
        "statusBarItem.remoteBackground": "#6E5CFF", "statusBarItem.remoteForeground": "#FFFFFF",
        "statusBarItem.hoverBackground": HOVER,
        "titleBar.activeBackground": DEEP, "titleBar.activeForeground": mix(DEEP, FG, 0.94),
        "titleBar.inactiveBackground": DEEP, "titleBar.inactiveForeground": mix(DEEP, FG, 0.45),
        "titleBar.border": BORDER,
        "panel.background": SIDE, "panel.border": BORDER, "panelTitle.activeBorder": ACC,
        "panelTitle.activeForeground": "#F4F3FF", "panelTitle.inactiveForeground": mix(SIDE, FG, 0.7),
        "input.background": SURFACE, "input.border": BORDER, "input.foreground": FG,
        "input.placeholderForeground": mix(SURFACE, FG, 0.45), "inputOption.activeBorder": ACC,
        "dropdown.background": SURFACE, "dropdown.border": BORDER,
        "button.background": "#6552F0", "button.foreground": "#FFFFFF", "button.hoverBackground": "#7766FF",
        "button.secondaryBackground": SEL_IN, "button.secondaryForeground": FG,
        "textLink.foreground": p["AZURE"], "textLink.activeForeground": p["CYAN"],
        "textCodeBlock.background": SURFACE, "textBlockQuote.background": SURFACE,
        "textBlockQuote.border": ACC, "textPreformat.foreground": p["GREEN"],
        "notifications.background": SIDE, "notifications.border": BORDER,
        "quickInput.background": SIDE, "quickInputList.focusBackground": SEL,
        "menu.background": SIDE, "menu.selectionBackground": SEL, "menu.border": BORDER,
        "peekView.border": ACC, "peekViewEditor.background": mix(BG, ACC, 0.04),
        "peekViewResult.background": SIDE, "peekViewTitle.background": SIDE,
        "peekViewEditor.matchHighlightBackground": ORANGE + "44",

        "gitDecoration.modifiedResourceForeground": "#FFC37A",
        "gitDecoration.untrackedResourceForeground": "#9CF27E",
        "gitDecoration.addedResourceForeground": "#9CF27E",
        "gitDecoration.deletedResourceForeground": RED,
        "gitDecoration.conflictingResourceForeground": PINK,
        "gitDecoration.ignoredResourceForeground": mix(SIDE, FG, 0.4),
        "scmGraph.foreground1": p["VIOLET"], "scmGraph.foreground2": p["CYAN"], "scmGraph.foreground3": ORANGE,
        "scmGraph.foreground4": PINK, "scmGraph.foreground5": p["TEAL"],
        "diffEditor.insertedTextBackground": "#7EE07A2E", "diffEditor.removedTextBackground": RED + "2E",
        "diffEditor.insertedLineBackground": "#7EE07A16", "diffEditor.removedLineBackground": RED + "16",

        "terminal.background": SIDE, "terminal.foreground": FG,
        "terminal.ansiBlack": mix(SIDE, FG, 0.14), "terminal.ansiBrightBlack": mix(SIDE, FG, 0.42),
        "terminal.ansiRed": RED, "terminal.ansiBrightRed": "#FFA3AC",
        "terminal.ansiGreen": p["GREEN"], "terminal.ansiBrightGreen": "#C2F5CC",
        "terminal.ansiYellow": p["YELLOW"], "terminal.ansiBrightYellow": "#F3E3A0",
        "terminal.ansiBlue": p["AZURE"], "terminal.ansiBrightBlue": "#A6D8FF",
        "terminal.ansiMagenta": p["VIOLET"], "terminal.ansiBrightMagenta": "#DDD6FF",
        "terminal.ansiCyan": p["CYAN"], "terminal.ansiBrightCyan": "#A6F3FA",
        "terminal.ansiWhite": mix(SIDE, FG, 0.85), "terminal.ansiBrightWhite": "#FFFFFF",
        "terminalCursor.foreground": "#FFFFFF",
        # Error Lens: текст ошибки в конце строки
        "errorLens.errorForeground": RED, "errorLens.errorBackground": RED + "14",
        "errorLens.warningForeground": ORANGE, "errorLens.warningBackground": ORANGE + "10",
        "errorLens.infoForeground": p["AZURE"], "errorLens.infoBackground": p["AZURE"] + "0D",
        "errorLens.hintForeground": p["TEAL"], "errorLens.hintBackground": "#00000000",
    }


def make_theme(slug):
    v = VARIANTS[slug]
    return {
        "$schema": "vscode://schemas/color-theme",
        "name": v["name"],
        "type": "dark",
        "semanticHighlighting": True,
        "colors": ui_colors(v["bgs"], v["pal"]),
        "tokenColors": [{"settings": {"foreground": v["pal"].get("CODE_FG", v["pal"]["FG"]), "background": v["bgs"]["bg"]}}]
                       + token_colors(v["pal"]),
        "semanticTokenColors": semantic(v["pal"]),
    }


# --- проверки ---------------------------------------------------------------------
NEEDS = {  # роль: (WCAG к фону, |APCA Lc|)
    "CODE_FG": (7.0, 60),
    **{k: (7.0, 60) for k in ROLE_KEYS + ["FG"]},
    "PINK": (7.0, 55),        # жирный
    "PINK_DIM": (6.0, 45),    # {{ }} — служебные символы
    "FG_DIM": (5.5, 45), "COMMENT": (5.5, 45), "RED": (7.0, 50),
}
PAIRS = [("VIOLET", "AZURE"), ("YELLOW", "GREEN"), ("TEAL", "GREEN"), ("TEAL", "CYAN"), ("TEAL", "YELLOW"),
         ("ORANGE", "CORAL"), ("GOLD", "CORAL"), ("GOLD", "YELLOW"), ("ORANGE", "YELLOW"), ("ORANGE", "GOLD"),
         ("AZURE", "CYAN"), ("PINK", "VIOLET"), ("VIOLET", "FG_DIM")]


def check():
    bad_default = []
    for slug, v in VARIANTS.items():
        b, p = v["bgs"], v["pal"]
        print(f"\n  {v['name']}: фон {b['bg']}, панель {b['side']}, самый тёмный {b['deep']}, строка {b['line']}")
        print(f"  {'роль':9s} {'цвет':8s}  WCAG  APCA  на строке курсора")
        bad = []
        for k, (w_need, a_need) in NEEDS.items():
            if v.get("vivid") and a_need >= 60:
                a_need = 50
            c = p[k]
            w, a, wl = wcag(c, b["bg"]), abs(apca(c, b["bg"])), wcag(c, b["line"])
            flag = ""
            if w < w_need or a < a_need or (k in ROLE_KEYS and wl < 6.0):
                flag = "  ⚠"
                bad.append(k)
            print(f"  {k:9s} {c}  {w:5.2f} {a:5.1f}  {wl:5.2f}{flag}")
        worst = min(PAIRS, key=lambda pr: delta_e(p[pr[0]], p[pr[1]]))
        print(f"  ближайшая пара ролей: {worst[0]}/{worst[1]} ΔE {delta_e(p[worst[0]], p[worst[1]]):.3f}")
        if bad:
            print(f"  ⚠ ниже нормы: {', '.join(bad)}")
            if slug == DEFAULT:
                bad_default = bad
    if bad_default:
        sys.exit(f"вариант по умолчанию не проходит проверку: {bad_default}")


def write_extension():
    if EXT.exists():
        shutil.rmtree(EXT)
    (EXT / "themes").mkdir(parents=True)
    shutil.copytree(SYNTAXES, EXT / "syntaxes")
    contributes = []
    order = [DEFAULT] + [s for s in VARIANTS if s != DEFAULT]
    for slug in order:
        fn = f"violet-ops-{slug}-color-theme.json"
        (EXT / "themes" / fn).write_text(json.dumps(make_theme(slug), ensure_ascii=False, indent=2), encoding="utf-8")
        contributes.append({"label": VARIANTS[slug]["name"], "uiTheme": "vs-dark", "path": f"./themes/{fn}"})
    pkg = {
        "name": "violet-ops", "displayName": "Violet Ops", "publisher": "drxinfra",
        "description": "Violet dark theme for DevOps code: Ansible modules, parameters and task keywords in "
                       "distinct colors, Jinja, Helm templates, Jenkins pipelines, Shell, Go, Python, SQL.",
        "version": VERSION, "license": "MIT", "icon": "icon.png",
        "engines": {"vscode": "^1.80.0"}, "categories": ["Themes"],
        "keywords": ["theme", "dark", "violet", "purple", "ansible", "jinja", "helm", "jenkins", "groovy",
                     "devops", "yaml", "kubernetes", "terraform"],
        "galleryBanner": {"color": "#151521", "theme": "dark"},
        "homepage": "https://drxinfra.ru/violet-ops.html",
        "repository": {"type": "git", "url": "https://github.com/drxinfra/violet-ops.git"},
        "bugs": {"url": "https://github.com/drxinfra/violet-ops/issues"},
        "contributes": {
            "themes": contributes,
            "grammars": [{"scopeName": "jenkins.dsl.injection", "path": "./syntaxes/jenkins-dsl.injection.json",
                          "injectTo": ["source.groovy"]}],
        },
    }
    (EXT / "package.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    for f in ("README.md", "CHANGELOG.md", "LICENSE", "icon.png"):
        shutil.copy2(ROOT / f, EXT / f)
    for old in ROOT.glob("violet-ops-*.vsix"):
        old.unlink()
    out = ROOT / f"violet-ops-{VERSION}.vsix"
    subprocess.run(["npx", "--yes", "@vscode/vsce@3.2.2", "package", "--no-dependencies", "-o", str(out)],
                   cwd=EXT, check=True)
    print("собрано:", out)
    return order


# --- превью на реальных файлах ------------------------------------------------
VSCODE_EXT = pathlib.Path("/Applications/Visual Studio Code.app/Contents/Resources/app/extensions")
USER_EXT = pathlib.Path.home() / ".vscode" / "extensions"
CHROME = pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
HELM_BRACKETS = [["{{-", "-}}"], ["{{-", "}}"], ["{{", "-}}"], ["{{", "}}"], ["{", "}"], ["[", "]"], ["(", ")"]]
DEFAULT_BRACKETS = [["{", "}"], ["[", "]"], ["(", ")"]]


def grammar_index():
    """scopeName → путь к грамматике и injectTo → [scopeName]: встроенные, установленные и свои."""
    grammars, injections = {}, {}
    dirs = sorted(VSCODE_EXT.iterdir()) + sorted(d for d in USER_EXT.iterdir() if "violet-ops" not in d.name) + [EXT]
    for d in dirs:
        pj = d / "package.json"
        if not pj.is_file():
            continue
        try:
            pkg = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            continue
        for g in pkg.get("contributes", {}).get("grammars", []):
            sc, p = g.get("scopeName"), g.get("path")
            if not sc or not p:
                continue
            grammars[sc] = str((d / p).resolve())
            for target in g.get("injectTo", []) or []:
                injections.setdefault(target, [])
                if sc not in injections[target]:
                    injections[target].append(sc)
    return grammars, injections


def render_preview(order):
    if not (RENDER / "node_modules" / "vscode-textmate").exists():
        print("превью пропущено: нет render/node_modules (cd render && npm install)")
        return
    samples = json.loads((RENDER / "samples.json").read_text(encoding="utf-8"))
    fix = lambda s: {**s, "file": str((ROOT / s["file"]).resolve())}
    grammars, injections = grammar_index()
    if PREVIEW.exists():
        shutil.rmtree(PREVIEW)
    PREVIEW.mkdir()
    spec = {
        "out": str(PREVIEW),
        "grammars": grammars, "injections": injections,
        "brackets": {"source.helm": HELM_BRACKETS, "default": DEFAULT_BRACKETS},
        "frame": fix(samples["frame"]),
        "samples": [fix(s) for s in samples["samples"]],
        "themes": [{"slug": s, "caption": "",
                    "path": str(EXT / "themes" / f"violet-ops-{s}-color-theme.json")} for s in order],
    }
    sp = PREVIEW / "spec.json"
    sp.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    subprocess.run(["node", str(RENDER / "render.js"), str(sp)], check=True)
    if not CHROME.exists():
        print("png не сняты: нет Google Chrome")
        return
    lines = [s["to"] - s["from"] + 1 for s in spec["samples"]]
    rows = [max(lines[i:i + 2]) for i in range(0, len(lines), 2)]       # сетка в две колонки
    code_h = int(40 + sum(60 + 23 * r * 1.1 for r in rows))               # 1.1 — запас на перенос строк
    for s in order:
        for kind, h in (("frame", 960), ("code", code_h)):
            subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size=1600,{h}", f"--screenshot={PREVIEW / f'{s}-{kind}.png'}",
                            f"file://{PREVIEW / f'{s}-{kind}.html'}"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("превью:", PREVIEW)


def shot(html_path, png_path, w, h, transparent=False):
    args = [str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
            f"--screenshot={png_path}"]
    if transparent:
        args.append("--default-background-color=00000000")
    subprocess.run(args + [f"file://{html_path}"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_icon():
    """icon.png 128×128 из images/icon.svg (Chrome headless, прозрачный фон)."""
    svg = ROOT / "images" / "icon.svg"
    page = ROOT / "images" / ".icon.html"
    page.write_text(f'<!doctype html><style>html,body{{margin:0;background:transparent}}</style>'
                    f'<img src="{svg.name}" width="128" height="128">', encoding="utf-8")
    shot(page, ROOT / "icon.png", 128, 128, transparent=True)
    page.unlink()


def readme_images(order):
    """Картинки для README и сайта: окно с Ansible, сетка языков, три варианта рядом."""
    img = ROOT / "images"
    shutil.copy2(PREVIEW / f"{DEFAULT}-frame.png", img / "ansible.png")
    shutil.copy2(PREVIEW / f"{DEFAULT}-code.png", img / "languages.png")
    cells = "".join(f'<div class="c"><div class="t">{VARIANTS[s]["name"]}</div>'
                    f'<div class="crop" style="background-image:url(\'{PREVIEW / (s + "-frame.png")}\')"></div></div>'
                    for s in order)
    page = PREVIEW / "variants.html"
    page.write_text(f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;background:#0b0b10;font:600 22px -apple-system,sans-serif;color:#e8e6f5;padding:18px}}
.g{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}} .t{{margin:0 0 8px}}
.crop{{height:620px;background-repeat:no-repeat;background-size:1400px auto;background-position:-300px -40px;
border-radius:8px;border:1px solid #2a2840}}</style><div class="g">{cells}</div>""", encoding="utf-8")
    shot(page, img / "variants.png", 1800, 690)


if __name__ == "__main__":
    check()
    make_icon()
    order = write_extension()
    if "--no-preview" not in sys.argv:
        render_preview(order)
        readme_images(order)
